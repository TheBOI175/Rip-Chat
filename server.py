from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rip-chat-secret-key'

socketio = SocketIO(app, cors_allowed_origins="*")

# Data structures
rooms = {}  # { room_code: { users: { sid: { username, socketId, muted } } } }
user_data = {}  # { sid: { username, room_code } }


def generate_room_code():
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    code = ''.join(random.choice(chars) for _ in range(6))
    if code in rooms:
        return generate_room_code()
    return code


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
        else:
            print(f'Room {room_code} now has {len(rooms[room_code]["users"])} user(s)')
    
    del user_data[sid]


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
    
    if not username or not isinstance(username, str):
        emit('error', 'Invalid username')
        return
    
    username = username.strip()[:20]
    if not username:
        emit('error', 'Username cannot be empty')
        return
    
    # Leave current room if in one
    if sid in user_data:
        handle_user_leave(sid)
    
    room_code = generate_room_code()
    
    rooms[room_code] = {'users': {}}
    rooms[room_code]['users'][sid] = {
        'username': username,
        'socketId': sid,
        'muted': False
    }
    user_data[sid] = {'username': username, 'room_code': room_code}
    
    join_room(room_code)
    emit('room-created', {'roomCode': room_code, 'username': username})
    print(f'Room {room_code} created by {username}')


@socketio.on('join-room')
def handle_join_room(data):
    sid = request.sid
    
    if not data or 'roomCode' not in data or 'username' not in data:
        emit('error', 'Invalid room code or username')
        return
    
    room_code = data['roomCode'].upper().strip()
    username = data['username'].strip()[:20]
    
    if not username:
        emit('error', 'Username cannot be empty')
        return
    
    if room_code not in rooms:
        emit('error', 'Room not found. Check the code and try again.')
        return
    
    # Leave current room if in one
    if sid in user_data:
        handle_user_leave(sid)
    
    existing_users = list(rooms[room_code]['users'].values())
    
    rooms[room_code]['users'][sid] = {
        'username': username,
        'socketId': sid,
        'muted': False
    }
    user_data[sid] = {'username': username, 'room_code': room_code}
    
    join_room(room_code)
    
    emit('room-joined', {
        'roomCode': room_code,
        'username': username,
        'existingUsers': existing_users
    })
    
    emit('user-joined', {
        'username': username,
        'socketId': sid,
        'muted': False
    }, to=room_code, skip_sid=sid)
    
    print(f'{username} joined room {room_code} ({len(rooms[room_code]["users"])} users)')


@socketio.on('mute-status')
def handle_mute_status(data):
    sid = request.sid
    
    if sid not in user_data:
        return
    
    muted = data.get('muted', False)
    room_code = user_data[sid]['room_code']
    
    if room_code and room_code in rooms and sid in rooms[room_code]['users']:
        rooms[room_code]['users'][sid]['muted'] = muted
        
        # Broadcast mute status to everyone in room
        emit('user-mute-changed', {
            'socketId': sid,
            'muted': muted
        }, to=room_code)


@socketio.on('offer')
def handle_offer(data):
    sid = request.sid
    target_id = data.get('targetId')
    offer = data.get('offer')
    
    if not target_id or not offer:
        return
    
    if sid in user_data:
        emit('offer', {
            'offer': offer,
            'fromId': sid,
            'fromUsername': user_data[sid]['username']
        }, to=target_id)


@socketio.on('answer')
def handle_answer(data):
    target_id = data.get('targetId')
    answer = data.get('answer')
    
    if not target_id or not answer:
        return
    
    emit('answer', {
        'answer': answer,
        'fromId': request.sid
    }, to=target_id)


@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    target_id = data.get('targetId')
    candidate = data.get('candidate')
    
    if not target_id:
        return
    
    emit('ice-candidate', {
        'candidate': candidate,
        'fromId': request.sid
    }, to=target_id)


@socketio.on('leave-room')
def handle_leave_room():
    handle_user_leave(request.sid)


# Health check
@app.route('/')
def index():
    return 'Rip Chat Server Running'


@app.route('/status')
def status():
    return {
        'status': 'online',
        'rooms': len(rooms),
        'users': len(user_data)
    }


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Rip Chat Server running on port {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
