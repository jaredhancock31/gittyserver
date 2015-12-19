import flask
import psycopg2
import os
import datetime
import time
from users import *
from contextlib import contextmanager, closing

app = flask.Flask(__name__)
app.config.from_pyfile('settings.py')
if os.path.exists('localsettings.py'):
    app.config.from_pyfile('localsettings.py')
subBug = 0

@contextmanager
def db_cursor():
    # Get the database connection from the configuration
    dbc = psycopg2.connect(**app.config['PG_ARGS'])

    try:
        cur = dbc.cursor()
        try:
            yield cur
        finally:
            cur.close()
    finally:

        dbc.commit()
        dbc.close()

@app.route('/')
def hello_world():
    if 'auth_user' in flask.session:
        # we have a user
        with db_cursor() as dbc:
            uid = flask.session['auth_user']
            user = get_user(uid)
            if user is None:
                app.logger.error('invalid user %d', uid)
                flask.abort(400)

            return flask.redirect('/home', code=303)
    else:
        return flask.render_template('login.html')


@app.route('/login', methods=['POST'])
def login():
    username = flask.request.form['user']
    password = flask.request.form['passwd']
    if username is None or password is None:
        flask.abort(400)
    action = flask.request.form['action']
    if action == 'Log in':
        uid = check_auth(username, password)
        if uid is not None:
            flask.session['auth_user'] = uid
            return flask.redirect('/home', code=303)
        else:
            flask.abort(403)
    elif action == 'Create account':
        Cusername = flask.request.form['Cuser']
        Cpassword = flask.request.form['Cpasswd']
        name = flask.request.form['Name']
        email = flask.request.form['Email']
        uid = create_user(Cusername, Cpassword, name, email)
        flask.session['auth_user'] = uid
        return flask.redirect('/home', code=303)

@app.route('/logout')
def logout():
    flask.session.pop('auth_user', None)
    flask.flash('You were logged out')
    return flask.redirect('/', code=303)

@app.route('/home')
def home_page():
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']
        with db_cursor() as cur:
            cur.execute('SELECT username from users '
                        'WHERE user_id = %s', (uid,))
            uName = cur.fetchone()

            # get mention and associated bug this user has been mentioned in
            cur.execute('''SELECT mentionee, comment_id, bug_id, text
                        FROM mention
                        LEFT OUTER JOIN comments USING (comment_id)
                        WHERE mentionee = %s
                        GROUP BY comment_id, mentionee, bug_id, text
                        ''', (uid,))
            mentions = []
            for other, cid, bid, text in cur:
                mentions.append({'other': other, 'cid': cid, 'bid': bid, 'text': text})

            # get bugs this user has been assigned
            cur.execute('''SELECT bug_id, title
                        FROM users
                        LEFT OUTER JOIN bug ON (user_id = assignee)
                        GROUP BY user_id, bug_id
                        HAVING user_id = %s''', (uid,))

            assigned = []
            for id, title in cur:
                assigned.append({'bid': id, 'title': title})

            # get bugs this user has created
            cur.execute('''SELECT bug_id, title
                        FROM users
                        LEFT OUTER JOIN bug ON (user_id = creator)
                        GROUP BY user_id, bug_id
                        HAVING user_id = %s''', (uid,))

            created = []
            for id, title in cur:
                created.append({'bid': id, 'title': title})

            # get subsciptions for this user
            cur.execute('''SELECT bug_id, title
                        FROM users
                        LEFT OUTER JOIN bug ON (user_id = creator)
                        LEFT OUTER JOIN subscription ON (bug_id = sub_bug_id)
                        GROUP BY user_id, bug_id, sub_user_id
                        HAVING sub_user_id = %s''', (uid,))

            subscribed = []
            for id, title in cur:
                subscribed.append({'bid': id, 'title': title})

        return flask.render_template('home.html', uName = uName, assigned = assigned,
                                     created = created, subscribed = subscribed, mentions = mentions)

    else: return flask.redirect('/')



@app.route('/bug/')
def bug_list():
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']
        with db_cursor() as cur:

            # get all bugs
            cur.execute('''SELECT bug_id, title FROM bug''')
            list_bugs = []
            for bug_id, title in cur:
                list_bugs.append({'bug_id': bug_id, 'title': title})

        return flask.render_template('buglist.html', list_bug=list_bugs)
    else: return flask.redirect('/')




@app.route('/bug/<int:bug_id>')
def bug_page(bug_id):
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']

        with db_cursor() as cur:

            # get user info for bug creator
            cur.execute('''SELECT bug_id, name, assignee, title,
                  creation_date, details, close_date, user_id FROM bug
                  JOIN users ON creator = user_id
                  WHERE bug_id = %s''' , (bug_id,))
            row = cur.fetchone()
            bug = {'bug_id': row[0], 'creator': row[1], 'assignee': row[2],
             'title': row[3], 'creation_date': row[4], 'details': row[5],
             'close_date': row[6], 'user_id': row[7]}
            global subBug
            subBug = row[0]

            # get the user info of the user assigned to this bug
            cur.execute('''SELECT name, user_id FROM users
                    join bug on assignee = user_id
                    where assignee = %s''', (row[2],))
            row = cur.fetchone()
            bug['assignee'] = row[0]
            assigneeID = row[1]

            # get comments about this bug
            cur.execute('SELECT bug_id, comment_id, author, post_date, text, username'
                  ' FROM comments'
                  ' JOIN users ON (user_id = author)'
                  ' WHERE bug_id = %s'
                  ' GROUP BY username, text, author, comment_id, bug_id, post_date '
                  ' ORDER BY post_date DESC',
                   (bug_id,))
            comments = []
            for bid, cid, author, date, text, user in cur:
                comments.append({'bid': bid, 'cid': cid, 'author': author, 'date': date, 'text': text, 'user': user})

        return flask.render_template('bug.html', bugs = bug, assigneeID = assigneeID,
                                     comments = comments)

    else:
        return flask.redirect('/')




@app.route('/bug/clog/<int:bug_id>')
def change_log(bug_id):
    bid = bug_id
    # print("inside changelog, bug_id: ", bid)

    with db_cursor() as cur:
        # get the changes for a specific bug
        cur.execute('''SELECT change_id, user_id, date_created, description
                FROM change
                LEFT OUTER JOIN bug USING (bug_id)
                WHERE bug_id = %s
                GROUP BY change_id
                ORDER BY date_created
                ''', (bid,))

        changes = []

        for cid, uid, date, desc in cur:
            changes.append({'cid':cid, 'uid':uid, 'date':date, 'desc':desc})

    return flask.render_template('change_log.html', changes=changes, bid=bid)




@app.route('/tag/')
def tag_list():
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']

        with db_cursor() as cur:
            # get all tags
           cur.execute('SELECT text, tag_id'
                   ' FROM tag'
                   ' GROUP BY text, tag_id')
           tags = []
           for word, id in cur:
               tags.append({'word': word, 'id': id})
        return flask.render_template('tagList.html',
                                tags=tags)
    else: return flask.redirect('/')



@app.route('/tag/<string:word>')
def tag_info(word):
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']

        with db_cursor() as cur:
            # get bug associated with this tag
            cur.execute('SELECT text, bug_id, title'
                   ' FROM tag'
                   ' JOIN bug USING (bug_id)'
                   ' WHERE text = %s'
                   ' GROUP BY bug_id, text, title',
                   (word,))

            tags = []
            for tagWord, bugid, title in cur:
                tags.append({'tagWord': tagWord, 'bugid': bugid, 'title': title})

        return flask.render_template('taginfo.html', word=word, tags=tags)

    else: return flask.redirect('/')



@app.route('/home/add_comment', methods=['POST'])
def add_comment():
   uid = flask.session['auth_user']
   action = flask.request.form['action']
   bug = flask.request.form['bid']
   if action == 'Submit Comment':
       with db_cursor() as cur:
           text = flask.request.form['comment']
           mentions = flask.request.form['mentions'].split(',') #list of mentions
           date = time.time()
           postdate = datetime.datetime.fromtimestamp(date).strftime('%Y-%m-%d %H:%M:%S')
           author = uid
           bug = flask.request.form['bid']

            # add comment into comment table
           cur.execute('''INSERT INTO comments (comment_id, author, bug_id, post_date, text)
                       VALUES (nextval('comments_comment_id_seq'), %s, %s, %s, %s)
                       RETURNING comment_id''',
                       (author, bug, postdate, text))

           cid = cur.fetchone()[0]  # get the comment id of the comment we just created

           for ment in mentions:

               # get user id of the username in the mention
               cur.execute('''SELECT user_id
                            FROM users
                            WHERE username = %s''', (ment,))

               mentionee_id = cur.fetchone()

                # add mention to mention table
               cur.execute('''INSERT INTO mention (mentionee, comment_id) VALUES (%s, %s)
               ''', (mentionee_id, cid))

   return flask.redirect(flask.url_for('bug_page', bug_id = bug))



@app.route('/users/')
def users():
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']

        with db_cursor() as cur:
            # get user and usernames
            cur.execute('''SELECT username, user_id
                        FROM users
                        ORDER BY username''')

            users = []
            for uName, user_id in cur:
                users.append({"uName": uName, "userId": user_id})

            return flask.render_template('users.html',
                                 users=users)

    else: return flask.redirect('/')




@app.route('/users/<int:user_id>')
def user_prof(user_id):
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']
        with db_cursor() as cur:

            # get user info for selected user
            cur.execute('''SElECT username, name, user_id
                            FROM users
                            WHERE (user_id = %s)''', (user_id,))
            row = cur.fetchone()
            if row is None:
                flask.abort(404)

            uName, name, userId = row
            user = {'uName': uName, 'name': name, 'uid': userId}

            # get bugs that this user is assigned to
            cur.execute('''SELECT bug_id, title
                        FROM users
                        LEFT OUTER JOIN bug ON (user_id = assignee)
                        GROUP BY user_id, bug_id
                        HAVING user_id = %s''', (user_id,))

            assigned = []
            for id, title in cur:
                assigned.append({'bid': id, 'title': title})

            # get bugs that this user has created
            cur.execute('''SELECT bug_id, title
                        FROM users
                        LEFT OUTER JOIN bug ON (user_id = creator)
                        GROUP BY user_id, bug_id
                        HAVING user_id = %s''', (user_id,))

            created = []
            for id, title in cur:
                created.append({'bid': id, 'title': title})

            return flask.render_template('user_prof.html', user=user, assigned=assigned, created=created)
    else: return flask.redirect('/')

@app.route('/subscribe')
def subscribe():
    if 'auth_user' in flask.session:
        uid = flask.session['auth_user']
        with db_cursor() as cur:
            # add sub into subscription table
            cur.execute('INSERT INTO subscription (sub_bug_id,sub_user_id)'
                        'VALUES (%s, %s)', (subBug, uid))

    return flask.redirect(flask.url_for('bug_page', bug_id = subBug))

@app.route('/home/submit_bug')
def submit_bug_form():
    return flask.render_template("create_bug.html")

@app.route('/home/submit_bug', methods=['POST'])
def submit_bug_form_post():
    uid = flask.session['auth_user']
    print("User: ", uid)
    action = flask.request.form['action']

    if action == 'Submit' :

        title = flask.request.form['title']
        details = flask.request.form['details']
        tags = flask.request.form['tags'].split('#')  # list of tags?
        assignee = flask.request.form['assignee']
        ts = time.time()
        creation_date = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        # print(creation_date)
        close_date = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        url = '/bug/'  # TODO add next bug id, use sequences somehow

        with db_cursor() as cur:

            # get user_id by username provided
            cur.execute('''SELECT user_id
                        FROM users
                        WHERE username = %s''', (assignee, ))
            assn_id = cur.fetchone()

            # add bug to bug table
            cur.execute('''INSERT INTO bug (bug_id, creator, assignee, title, creation_date, details,close_date, url)
                        VALUES (nextval('bug_bug_id_seq'), %s, %s, %s, %s, %s, %s, %s)
                        RETURNING bug_id''', (uid, assn_id, title, creation_date, details, close_date, url))

            bid = cur.fetchone()[0]  # get the bug id of the bug we just created

            # add tags into tag table
            for tag in tags:
                cur.execute('''INSERT INTO tag (tag_id, bug_id, text) VALUES (nextval('tag_tag_id_seq'), %s, %s)
                ''', (bid, tag.strip().lower()))
    return flask.redirect('/home')

if __name__ == '__main__':
    app.run()
