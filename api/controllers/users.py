import bottle
import sqlalchemy as db
from datetime import datetime, timedelta
import uuid
import os

import common.auth as _auth
import common.helpers as util
import common.mail_service as mail

from models.user import UserModel
from models.model import ModelModel

import json
import logging

@bottle.get('/users')
#@_auth.requires_auth
#def users(credentials):
def users():
    u = UserModel()
    users = u.list()
    return json.dumps(users)

@bottle.get('/users/<id:int>')
@_auth.requires_auth
def get_user(credentials, id):
    u = UserModel()
    user = u.get(id)
    if not user:
        bottle.abort(404, 'Not found')

    if id != credentials['id']:
        # only copy some sub fields if this is not us
        nu, u = {}, user.to_dict()
        for f in ['id', 'username', 'affiliation']:
            nu[f] = u[f]
        return json.dumps(nu)
    else:
        return json.dumps(user.to_dict())

@bottle.put('/users/<id:int>')
def update_user(id):
    return bottle.template('<b>Hello {{id}}</b>!', id=id)

@bottle.post('/users')
def create_user():
    u = UserModel()
    data = bottle.request.json
    if not data or 'email' not in data or 'password' not in data or 'username' not in data:
        logging.info('Missing data')
        bottle.abort(400, 'Missing data')
    if u.exists(email=data['email']):
        logging.info('Email already exists')
        bottle.abort(409, 'Email already exists')
    elif u.exists(username=data['username']):
        logging.info('Username already exists')
        bottle.abort(409, 'Username already exists')

    try:
        u.create(email=data['email'], password=data['password'], username=data['username'])
        user = u.getByEmail(data['email'])
        refresh_token = _auth.set_refresh_token()
        u.update(user.id, {'refresh_token': refresh_token})
    except Exception as error_message:
        logging.info('Could not create user: %s' % (error_message))
        bottle.abort(400, 'Could not create user: %s' % (error_message))

    token = _auth.get_token({'id': user.id, 'username': user.username})
    logging.info('Registration and authentication successful for %s' % (user.username))
    return {'user': user.to_dict(), 'token': token}

@bottle.post('/recover/resolve/<forgot_token>')
def reset_password(forgot_token):
    """
    Validate forgot password token and update new password in user
    In token validation we used the forgot password token expiry date and time column
    :param forgot_token:
    :return: Success or Error
    """

    data = bottle.request.json
    if not data or 'password' not in data or 'email' not in data:
        logging.info('Missing data')
        bottle.abort(400, 'Missing data')
    try:
        u = UserModel()
        user = u.getByForgotPasswordToken(forgot_password_token=forgot_token)
        if not user:
            raise AssertionError('Invalid token')
        if datetime.now() > user.forgot_password_token_expiry_date:
            raise AssertionError('Invalid token')
        if user.email != data['email']:
            raise AssertionError('Invalid user')

        user.set_password(data['password'])
        u.update(user.id, {'forgot_password_token': None, 'forgot_password_token_expiry_date': None,
                           'password': user.password})
    except AssertionError as e:
        logging.exception('Invalid token : %s' % (e))
        bottle.abort(401, str(e))
    except Exception as error_message:
        logging.exception('Could not reset user password: %s' % (error_message))
        bottle.abort(400, 'Could not reset user password: %s' % (error_message))

    logging.info('User password reset successful for %s' % (user.username))
    return {'status': 'successful'}

@bottle.post('/recover/initiate')
def recover_password():
    """
    Generate forgot password token and send email to respective user
    The reset password host reads from  requested url
    :return: Success if true else raise exception
    """

    data = bottle.request.json
    if not data or 'email' not in data:
        bottle.abort(400, 'Missing email')

    u = UserModel()
    user = u.getByEmail(email=data['email'])
    if not user:
        return {'status': 'success'}
    try:
        # issuing new forgot password token
        forgot_password_token = u.generate_password_reset_token()
        expiry_datetime = datetime.now() + timedelta(hours=4)
        u.update(user.id, {'forgot_password_token': forgot_password_token,
                           'forgot_password_token_expiry_date': expiry_datetime})
        #  send email
        subject = 'Password reset link requested'
        msg = {'ui_server_host': util.parse_url(bottle.request.url), 'token': forgot_password_token}
        mail.send(server=bottle.default_app().config['mail'], contacts=[user.email],
                  template_name=bottle.default_app().config['forgot_pass_template'], msg_dict=msg, subject=subject)
        return {'status': 'success'}
    except Exception as error_message:
        logging.exception("Reset password failure (%s)" % (data['email']))
        bottle.abort(403, 'Reset password failed : %s' % (error_message))

@bottle.get('/users/<uid:int>/models')
def get_user_models(uid):
    """
    Fetch all user models based on user id
    :param uid:
    :return: Json Object
    """
    # check the current user and request user id are same
    is_current_user = util.is_current_user(uid=uid)
    logging.info('Current user validation status (%s) for %s' %(is_current_user, uid))
    limit, offset = util.get_limit_and_offset_from_request()
    try:
        model = ModelModel()
        results, total_count = model.getUserModelsByUid(uid=uid, is_current_user=is_current_user, n=limit, offset=offset)
        dicts = [model_obj.to_dict() for model_obj in results]
        if dicts:
            return json.dumps({'count': total_count, 'data': dicts})
        return json.dumps({'count': 0, 'data': []})
    except Exception as e:
        logging.exception('Could not fetch user model(s) : %s' % (e))
        bottle.abort(400, 'Could not fetch user model(s)')

@bottle.get('/users/<uid:int>/models/<model_id:int>')
def get_user_models(uid, model_id):
    """
    Get users specific model detail
    :param uid: User Id
    :param model_id: Model Id
    :return: Json Object
    """
    # check the current user and request user id are same
    is_current_user = util.is_current_user(uid= uid)
    logging.info('Current user validation status (%s) for %s' %(is_current_user, uid))
    try:
        model = ModelModel()
        model_obj = model.getUserModelsByUidAndMid(uid=uid, mid=model_id, is_current_user=is_current_user)
        dicts = model_obj.to_dict()
        if dicts:
            return json.dumps(dicts)
    except Exception as e:
        logging.exception('Could not fetch user model: %s' % (e))
        bottle.abort(400, 'Could not fetch user model')

    bottle.abort(204, 'No models found')

@bottle.put('/users/<id:int>/profileUpdate')
@_auth.requires_auth
def update_user_profile(credentials, id):
    """
    Update user profile details like  real name, affiliation  and user name
    :param credentials: Authentication detail
    :param id: User id
    :return: Json Object
    """
    data = bottle.request.json
    user = UserModel()
    if not util.check_fields(data, ['username', 'affiliation', 'realname']):
        bottle.abort(400, 'Missing data')

    # validate user detail
    if not util.is_current_user(uid=id, credentials=credentials):
        bottle.abort(403, 'Not authorized to update profile')
    try:
        u = user.get(id)
        user.update(u.id, {'username': data['username'], 'affiliation': data['affiliation'],
                        'realname': data['realname']})
        return json.dumps(u.to_dict())
    except db.orm.exc.NoResultFound as ex:
        bottle.abort(404, 'User Not found')
    except Exception as ex:
        logging.exception('Could not update profile: %s' % (ex))
        bottle.abort(400, 'Could not update profile: %s' % (ex))

@bottle.post('/users/<id:int>/avatar/upload')
@_auth.requires_auth
def upload_user_profile_picture(credentials, id):
    """
    Update user profile details like  real name, affiliation  and user name
    :param credentials: Authentication detail
    :param id: User id
    :return: Json Object
    """

    u = UserModel()
    upload = bottle.request.files.get('file')
    app = bottle.default_app()
    s3_service = app.config['s3_service']
    file_name, ext = os.path.splitext(upload.filename)

    # validating file extension
    if ext not in ('.png', '.jpg', '.jpeg'):
        bottle.abort(400, 'File extension not allowed.')
    # validate and read the file
    img_byte_str = util.read_file_content(upload.file, app.config['profile_img_max_size'])

    # validate user detail
    if not util.is_current_user(uid=id, credentials=credentials):
        bottle.abort(403, 'Not authorized to update profile')
    try:
        user = u.get(id)
        if not user:
            bottle.abort(403, 'Not authorized to update profile picture')
        pic_url = user.avatar_url
        # removing old avatar picture from s3 bucket
        if pic_url and pic_url != '':
            s3_service.delete_object(Bucket=app.config['aws_s3_bucket_name'], Key='profile/' + pic_url.split('/')[-1])
        # upload new avatar picture with new uuid into s3 bucket
        file_name = str(uuid.uuid4()) + ext
        s3_service.put_object(Body=img_byte_str, Bucket=app.config['aws_s3_bucket_name'], Key='profile/' + file_name,
                              ACL='public-read', ContentType=upload.content_type)
        # update avatar s3 ur in user object
        base_url = app.config['aws_s3_profile_base_url'] + '/profile/' + file_name
        u.update(user.id, {'avatar_url': base_url})
        return json.dumps(user.to_dict())
    except db.orm.exc.NoResultFound as ex:
        bottle.abort(404, 'User Not found')
    except Exception as ex:
        logging.exception('Could not upload user profile picture: %s' % (ex))
        bottle.abort(400, 'Could not upload user profile picture')
