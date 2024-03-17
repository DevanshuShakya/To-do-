import json
import logging
from flask_sqlalchemy import SQLAlchemy
from flask import Flask, g, render_template, redirect, url_for, request
from flask_oidc import OpenIDConnect
from keycloak import keycloak_openid
import requests, os
from sqlalchemy import text

import stripe


current_dir=os.path.abspath(os.path.dirname(__file__))

db = SQLAlchemy()

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config.update({
    'SECRET_KEY': 'SomethingNotEntirelySecret',
    'TESTING': True,
    'DEBUG': True,
    'OIDC_CLIENT_SECRETS': 'client_secrets.json',
    'OIDC_ID_TOKEN_COOKIE_SECURE': False,
    'OIDC_USER_INFO_ENABLED': True,
    'OIDC_OPENID_REALM': 'dendrite',
    'OIDC_SCOPES': ['openid', 'email', 'profile'],
    'OIDC_INTROSPECTION_AUTH_METHOD': 'client_secret_post',
    'STRIPE_SECRET_KEY': 'super_secret'
})

import os

os.environ['STRIPE_SECRET_KEY'] = 'super_secret'
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///"+os.path.join(current_dir,"todo.sqlite3")
db.init_app(app)

oidc = OpenIDConnect(app)

app.app_context().push()

class User(db.Model):
    _tablename_='user'
    keycloak_id=db.Column(db.String, primary_key= True)
    cust_id=db.Column(db.String)
    pro= db.Column(db.Integer)

class Todo(db.Model):
    _tablename_='todo'
    task_id=db.Column(db.Integer, primary_key= True, autoincrement=True)
    id=db.Column(db.Integer, nullable=False)
    title=db.Column(db.String, nullable=False)
    description=db.Column(db.String, nullable=False)
    time=db.Column(db.String)
from datetime import datetime, timedelta

def month_later_utc(utc_timestamp):
    utc_datetime = datetime.utcfromtimestamp(utc_timestamp)
    one_month_later = utc_datetime + timedelta(days=30)
    month_later_utc_timestamp = int(one_month_later.timestamp())
    return month_later_utc_timestamp

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/todo')
@oidc.require_login
def todo():
    if request.method=='GET':
        query=text("""select * from todo where id='{}'""".format(oidc.user_getfield('sub')))
        results= db.session.execute(query).fetchall()
        user= User.query.filter(User.keycloak_id==oidc.user_getfield('sub')).first()


    def get_payments():
        payments = stripe.PaymentIntent.list()
        return payments

    def get_customers():
        customers = stripe.Customer.list()
        return customers
    

    details={}
 
    customers = get_customers()
    for customer in customers:
        if customer['email']==oidc.user_getfield('email'):
            details['email']= customer['email']
            details['name']= customer['name']
            details['customer_id']= customer['id']
            break
    if len(details)==0:
        user= User.query.filter(User.keycloak_id==oidc.user_getfield('sub')).first()
        if user==None:        
            user= User(keycloak_id=oidc.user_getfield('sub'), pro= 0)
            db.session.add(user)
            db.session.commit()
        return render_template('todolist.html', username=oidc.user_getfield('preferred_username'), tasks= results, user= user)


    # Get all payments
    payments = get_payments()
    for payment in payments:
        if details['customer_id']==payment['customer']:
            details['start_date']=payment['payment_method_options']['card']['mandate_options']['start_date']
            details['amount_received']=payment['amount_received']
            details['created']=payment['created']
            details['status']=payment['status']
            details['invoice']=payment['invoice']

    if details['status']== 'succeeded':

        if int(datetime.now().timestamp())<=month_later_utc(details['start_date']):
            if user.pro==0:
                user.pro=1
                db.session.commit()
        else:
            if user.pro==1:
                user.pro=0
                db.session.commit()
    
    return render_template('todolist.html', username=oidc.user_getfield('preferred_username'), tasks= results, user= user)

@app.route('/private')
@oidc.require_login
def profile():
    info = oidc.user_getinfo(['preferred_username', 'email', 'sub'])

    username = info.get('preferred_username')
    email = info.get('email')
    user_id = info.get('sub')

    user= User.query.filter(User.keycloak_id==user_id).first()

    return render_template('profile.html',user= user, email=email, user_id= user_id, username= username)

from PIL import Image

def crop_image(image_path):
    image = Image.open(image_path)

    width, height = image.size
    desired_ratio = 173.5 / 150
    image_ratio = width / height

    if image_ratio > desired_ratio:
        new_width = int(height * desired_ratio)
        new_height = height
    else:
        new_width = width
        new_height = int(width / desired_ratio)

    left = (width - new_width) // 2
    top = (height - new_height) // 2
    right = left + new_width
    bottom = top + new_height

    cropped_image = image.crop((left, top, right, bottom))

    return cropped_image


def rename_file_in_static_folder(folder_path, old_name, new_name):
        old_file_path = os.path.join(folder_path, old_name)
        new_file_path = os.path.join(folder_path, new_name)

        try:
            os.rename(old_file_path, new_file_path)
            print(f"File '{old_name}' in '{folder_path}' has been renamed to '{new_name}' successfully.")
        except FileNotFoundError:
            print(f"Error: File '{old_name}' not found in '{folder_path}'.")
        except PermissionError:
            print(f"Error: Permission denied to rename '{old_name}' in '{folder_path}'.")
        except OSError as e:
            print(f"Error: {e}")

@app.route('/deletetodo/<int:task_id>')
@oidc.require_login
def deletetodo(task_id):
    query= text("""delete from todo where task_id={} and id='{}'""".format(task_id, oidc.user_getfield('sub')))
    db.session.execute(query)
    db.session.commit()
    return redirect(url_for('todo'))


@app.route('/addtodo', methods=['GET','POST'])
@oidc.require_login
def addtodo():
    user= User.query.filter(User.keycloak_id==oidc.user_getfield('sub')).first()
    if request.method=='GET':
        return render_template('task.html', user= user)

    elif request.method=='POST':
        title= request.form['title']
        description= request.form['description']
        time= request.form['time']
        user_id= oidc.user_getfield('sub')
        # pro=0

        if user.pro==0:
            task=Todo(id= user_id ,title= title, description= description, time= time)
            db.session.add(task)
            db.session.commit()

            return redirect(url_for('todo'))
            
        
        image= request.files['image']

        if image.filename!='':
            img = Image.open(image)
            img = img.convert("RGB")
        
            image_name=str(user_id+title+time[:2]+time[3:]+'.jpeg')
        
            img.save('static/{}'.format(image_name))
            cropped_image = crop_image('static/{}'.format(image_name))

            cropped_image.save('static/{}'.format(image_name))
            
        
        
        task=Todo(id= user_id ,title= title, description= description, time= time)
        db.session.add(task)
        db.session.commit()

        return redirect(url_for('todo'))

@app.route('/edittodo/<int:task_id>', methods=['GET','POST'])
@oidc.require_login
def edittodo(task_id):
    user= User.query.filter(User.keycloak_id==oidc.user_getfield('sub')).first()
    task= Todo.query.filter(Todo.id==oidc.user_getfield('sub'),Todo.task_id==task_id).first()
    if request.method=='GET':
        return render_template('task.html', task= task, user= user) 
    elif request.method=='POST':
        title= request.form['title']
        description= request.form['description']
        if description!='':
            task.description= request.form['description']
           
        
        time= request.form['time']
        task.user_id= oidc.user_getfield('sub')
        user_id= oidc.user_getfield('sub')

        if user.pro==0:
            task.title=title
            task.time= time 
            db.session.commit()
            return redirect(url_for('todo'))
        
        image=request.files['image']


        if title!= task.title or time!=task.time:
            rename_file_in_static_folder("static", str(user_id+task.title+task.time[:2]+task.time[3:]+'.jpeg'), str(user_id+title+time[:2]+time[3:]+'.jpeg'))
        

        if image.filename!='':
            img = Image.open(image)
            img = img.convert("RGB")
        
            image_name=str(user_id+task.title+task.time[:2]+task.time[3:]+'.jpeg')
        
            img.save('static/{}'.format(image_name))
            cropped_image = crop_image('static/{}'.format(image_name))

            cropped_image.save('static/{}'.format(image_name)) 
        task.title=title
        task.time= time 
        db.session.commit()
        return redirect(url_for('todo'))

# GraphQL API
    
from flask_graphql import GraphQLView
import graphene

class Task(graphene.ObjectType):
    task_id= graphene.Int()
    id= graphene.String()
    title= graphene.String()
    description= graphene.String()
    time= graphene.String()

class Query(graphene.ObjectType):
    all_tasks= graphene.List(Task)

    def resolve_all_tasks(self, info):
        user_info= info.context.get('user')
        query= text("""select * from todo where id='{}'""".format(user_info))
        tasks= db.session.execute(query).fetchall()
        return [Task(task[0], task[1], task[2], task[3], task[4]) for task in tasks]
    

class CreateTask(graphene.Mutation):
    class Arguments:
        title = graphene.String()
        description = graphene.String()
        time = graphene.String()

    task = graphene.Field(Task)

    def mutate(self, info, title, description, time):
        new_task=Todo(id= info.context.get('user') ,title= title, description= description, time= time)
        db.session.add(new_task)
        db.session.commit()

        return CreateTask(task=Task(new_task.task_id ,new_task.id, new_task.title, new_task.description, new_task.time))
    
class EditTask(graphene.Mutation):
    class Arguments:
        task_id = graphene.Int(required=True)
        title = graphene.String()
        description = graphene.String()
        time = graphene.String()

    task = graphene.Field(Task)

    def mutate(self, info, task_id, title=None, description=None, time=None):
        task= Todo.query.filter(Todo.id==info.context.get('user'),Todo.task_id==task_id).first()
        if title is not None:
            task.title= title
        if description is not None:
            task.description= description
        if time is not None:
            task.time= time 

        if title is not None:
            if time is not None:
                # title changed and time changed
                rename_file_in_static_folder("/static", str(info.context.get('user')+task.title+task.time[:2]+task.time[3:]+'.jpeg'), str(info.context.get('user')+title+time[:2]+time[3:]+'.jpeg'))
            else:
                # title changed and time not changed
                rename_file_in_static_folder("/static", str(info.context.get('user')+task.title+task.time[:2]+task.time[3:]+'.jpeg'), str(info.context.get('user')+title+task.time[:2]+task.time[3:]+'.jpeg'))
        else:
            if time is not None:
                # title not changed and time changed
                rename_file_in_static_folder("/static", str(info.context.get('user')+task.title+task.time[:2]+task.time[3:]+'.jpeg'), str(info.context.get('user')+task.title+time[:2]+time[3:]+'.jpeg'))
            else:
                # title not changed and time not changed
                rename_file_in_static_folder("/static", str(info.context.get('user')+task.title+task.time[:2]+task.time[3:]+'.jpeg'), str(info.context.get('user')+task.title+task.time[:2]+task.time[3:]+'.jpeg'))


        db.session.commit()

        return EditTask(task= Task(task.task_id, task.id, task.title, task.description, task.time))
    
class DeleteTask(graphene.Mutation):
    class Arguments:
        task_id = graphene.Int(required=True)

    task_id = graphene.Int()

    def mutate(self, info, task_id):
        query= text("""delete from todo where task_id={} and id='{}'""".format(task_id, info.context.get('user')))
        db.session.execute(query)
        db.session.commit()
        return DeleteTask(task_id=task_id)
    
class Mutation(graphene.ObjectType):
    create_task = CreateTask.Field()
    edit_task = EditTask.Field()
    delete_task = DeleteTask.Field()
    
# GraphQL endpoint
@app.route('/graphql', methods=['GET','POST'])
@oidc.require_login
def graphql():
    schema = graphene.Schema(query=Query, mutation= Mutation)
    view = GraphQLView.as_view('graphql', schema=schema, graphiql=True, get_context=lambda: {'session': db.session, 'user': oidc.user_getfield('sub')})
    return view()



@app.route('/logout')
@oidc.require_login
def logout():
    refresh_token = oidc.get_refresh_token()
    oidc.logout()
    keycloak_openid.logout(refresh_token)
    response = redirect(url_for('login'))
    return response

if __name__ == '__main__':
    app.run()