from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rip-chat-secret-key'

# Allow all origins for CORS (needed for standalone HTML files)
socketio = SocketIO(app, cors_allowed_origins="*")

# Data structures
rooms = {}  # { room_code: { users: { sid: { username, sid } } } }
user_data = {}  # { sid: { username, room_code } }


def generate_room_code():
    """Generate a random 6-character room code"""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choice(chars) for _ in range(6))


@socketio.on('connect')
def handle_connect():
    print(f'User connected: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f'User disconnected: {sid}')
    handle_user_leave(sid)


@socketio.on('create-room')
def handle_create_room(username):
    sid = request.sid
    room_code = generate_room_code()
    
    rooms[room_code] = {'users': {}}
    rooms[room_code]['users'][sid] = {'username': username, 'socketId': sid}
    user_data[sid] = {'username': username, 'room_code': room_code}
    
    join_room(room_code)
    emit('room-created', {'roomCode': room_code, 'username': username})
    print(f'Room {room_code} created by {username}')


@socketio.on('join-room')
def handle_join_room(data):
    sid = request.sid
    room_code = data['roomCode'].upper()
    username = data['username']
    
    if room_code not in rooms:
        emit('error', 'Room not found. Check the code and try again.')
        return
    
    existing_users = list(rooms[room_code]['users'].values())
    
    rooms[room_code]['users'][sid] = {'username': username, 'socketId': sid}
    user_data[sid] = {'username': username, 'room_code': room_code}
    
    join_room(room_code)
    
    emit('room-joined', {
        'roomCode': room_code,
        'username': username,
        'existingUsers': existing_users
    })
    
    emit('user-joined', {
        'username': username,
        'socketId': sid
    }, to=room_code, skip_sid=sid)
    
    print(f'{username} joined room {room_code}')


@socketio.on('offer')
def handle_offer(data):
    sid = request.sid
    target_id = data['targetId']
    
    if sid in user_data:
        emit('offer', {
            'offer': data['offer'],
            'fromId': sid,
            'fromUsername': user_data[sid]['username']
        }, to=target_id)


@socketio.on('answer')
def handle_answer(data):
    emit('answer', {
        'answer': data['answer'],
        'fromId': request.sid
    }, to=data['targetId'])


@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    emit('ice-candidate', {
        'candidate': data['candidate'],
        'fromId': request.sid
    }, to=data['targetId'])


@socketio.on('leave-room')
def handle_leave_room():
    handle_user_leave(request.sid)


def handle_user_leave(sid):
    if sid not in user_data:
        return
    
    username = user_data[sid]['username']
    room_code = user_data[sid]['room_code']
    
    if room_code and room_code in rooms:
        if sid in rooms[room_code]['users']:
            del rooms[room_code]['users'][sid]
        
        emit('user-left', {
            'socketId': sid,
            'username': username
        }, to=room_code)
        
        leave_room(room_code)
        
        if len(rooms[room_code]['users']) == 0:
            del rooms[room_code]
            print(f'Room {room_code} deleted (empty)')
    
    del user_data[sid]


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Rip Chat Server running on port {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
