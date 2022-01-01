import webbrowser
from threading import Timer

from flask import Flask, render_template
from flask import request
from flask_socketio import SocketIO
import os
import time
import threading
app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def hello():
    return render_template('index.html')

def open_browser():
    webbrowser.open_new('http://127.0.0.1:2000/')

def run_engine():
    os.system("python3 engine.py")

open_browser()

t = threading.Thread(target=run_engine)
t.daemon = True
t.start()
print('got here')
@socketio.on('connected')
def connected():
    print('test 1')

@socketio.on('webpage_connected')
def connected(message):
    print('test 2')
@socketio.on('update_round_state')
def update_round_state(data):
    socketio.emit('update_round_state_webpage',data)
@socketio.on('new_round_state')
def new_round_state(data):
    socketio.emit('new_round_state_webpage',data)
@socketio.on('end_round_state')
def new_round_state(data):
    socketio.emit('end_round_state_webpage',data)
@socketio.on('CheckActionWebpage')
def CheckAction():
    socketio.emit('return_CheckAction', broadcast = True, include_self = False)
@socketio.on('FoldActionWebpage')
def FoldAction():
    socketio.emit('return_FoldAction', broadcast = True, include_self = False)
@socketio.on('CallActionWebpage')
def CallAction():
    socketio.emit('return_CallAction', broadcast = True, include_self = False)
@socketio.on('ConfirmRaise')
def ConfirmRaise(data):
    socketio.emit('return_RaiseAction', data,broadcast = True, include_self = False)
socketio.run(app, port=2000)