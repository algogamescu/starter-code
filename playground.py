from threading import Timer

from flask import Flask, send_from_directory
from flask import request
from flask_socketio import SocketIO
import os
import time
import threading

import logging

app = Flask(__name__, static_url_path='/static')

socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/<path:path>')
def send(path):
    return send_from_directory('static', path)

def run_engine():
    os.system("python3 engine.py")

t = threading.Thread(target=run_engine)
t.daemon = True
t.start()

playground_last_pushed = None

@socketio.on('player_connected')
def connected():
    print('[SOCKET] Bot Backend Connected')

@socketio.on('playground_connected')
def playground_connected():
    print('[SOCKET] Playground Connected')

# Handle a state refresh
@socketio.on('playground_request_refresh')
def playground_request_refresh():
    global playground_last_pushed

    print('[SOCKET] Playground requested refresh')
    
    if playground_last_pushed is not None:
        print('[SOCKET] Playground provided with refresh', playground_last_pushed)
        socketio.emit(playground_last_pushed[0], playground_last_pushed[1])

# Handle a new round occuring
@socketio.on('player_new_round_state')
def player_new_round_state(data):
    global playground_last_pushed

    print('[SOCKET] Player given new round, sent to playground')

    playground_last_pushed = ('playground_new_round_state', data) 
    socketio.emit('playground_new_round_state', data)

# Handle an update in the round state
@socketio.on('player_update_round_state')
def player_update_round_state(data):
    global playground_last_pushed

    print('[SOCKET] Player updated round state, sent to playground')

    playground_last_pushed = ('playground_update_round_state', data) 
    socketio.emit('playground_update_round_state', data)

# Handle the end of a round
@socketio.on('player_end_round_state')
def player_end_round_state(data):
    global playground_last_pushed

    print('[SOCKET] Player ended the round, sent to playground')

    playground_last_pushed = ('player_end_round_state', data)
    socketio.emit('playground_end_round_state', data)

# @socketio.on('update_round_state')
# def update_round_state(data):
#     socketio.emit('update_round_state_webpage',data)

# @socketio.on('new_round_state')
# def new_round_state(data):
#     socketio.emit('new_round_state_webpage',data)

# @socketio.on('end_round_state')
# def new_round_state(data):
#     socketio.emit('end_round_state_webpage',data)

@socketio.on('playground_act_check')
def CheckAction():
    socketio.emit('player_act_check', broadcast = True, include_self = False)

@socketio.on('playground_act_fold')
def FoldAction():
    print('FOLDDDD')
    socketio.emit('player_act_fold', broadcast = True, include_self = False)

@socketio.on('playground_act_call')
def CallAction():
    socketio.emit('player_act_call', broadcast = True, include_self = False)

@socketio.on('playground_act_raise')
def CallAction(data):
    socketio.emit('player_act_raise', broadcast = True, include_self = False, data=data)


# @socketio.on('hydrate')
# def Hydrate():
#     print('Hydration Requested')
#     socketio.emit('hydration_data', broadcast = True, include_self = False)
#     # socketio.emit('hydrate_action', broadcast = True, include_self = False)

# @socketio.on('ConfirmRaise')
# def ConfirmRaise(data):
#     socketio.emit('return_RaiseAction', data,broadcast = True, include_self = False)

socketio.run(app, port=2000)
