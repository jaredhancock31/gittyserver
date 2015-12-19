from projectserver import db_cursor

def get_user(uid):
    """
    Get a user's information.
    :param dbc: A database connection. This function will make and commit a transaction.
    :param uid: The user ID.
    :return: The user information map, or None if the user is invalid.
    """
    with db_cursor() as cur:
        cur.execute('''
            SELECT username
            FROM users WHERE user_id = %s
        ''', (uid,))
        row = cur.fetchone()
        if row is None:
            return None
        else:
            name, = row
            return {'name': name, 'id': uid }


def lookup_user(name):
    """
    Look up a user by name.
    :param dbc: A database connection. This function will take a transaction.
    :param uid: The user ID.
    :return: The user information map, or None if the user is invalid.
    """
    with db_cursor() as cur:
        cur.execute('''
            SELECT user_id, username, pass_word
            FROM users WHERE username = %s
        ''', (name,))
        row = cur.fetchone()
    if row is None:
        return None
    else:
        uid, name, password = row
        return {'id': uid,'name': name, 'password': password}


def check_auth(username, password):
    """
    Check if a user is authorized.
    :param dbc: The database connection.
    :param username: The user name.
    :param password: The password (unhashed).
    :return: The user ID, or None if authentication failed.
    """
    user = lookup_user(username)
    if user is None:
        return None
    elif user is not None:
        pw = user['password']
        if password == pw:
            return user['id']
        else:
            return None


def create_user(username, password, name, email):
    """
    Creates a user.
    :param dbc: The DB connection.  This function will make and commit a transaction.
    :param username: The user name.
    :param password: The password.
    :return: The user ID.
    """
    with db_cursor() as cur:
        cur.execute('''SELECT user_id FROM users
                    where user_id =(SELECT max(user_id) FROM users)''')
        row = cur.fetchone()
        uid = row[0]
        uid = uid+1
        prof_url = '/users/' + str(uid)
        cur.execute('''INSERT INTO users (user_id, name, username, pass_word, email,prof_url)
                    VALUES(%s, %s, %s, %s, %s, %s)''',
                    (uid, name, username, password, email,prof_url))
        cur.execute('''SELECT user_id FROM users
                    where user_id =(SELECT max(user_id) FROM users)''')
        row = cur.fetchone()
        uid = row[0]
        return uid
