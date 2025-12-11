from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import string
import os

app = Flask(__name__, static_folder='public')
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


# Serve the HTML file
@app.route('/')
def index():
    return send_from_directory('public', 'index.html')


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
    
    # Create the room
    rooms[room_code] = {'users': {}}
    rooms[room_code]['users'][sid] = {'username': username, 'socketId': sid}
    
    # Track user data
    user_data[sid] = {'username': username, 'room_code': room_code}
    
    # Join the socket.io room
    join_room(room_code)
    
    emit('room-created', {'roomCode': room_code, 'username': username})
    print(f'Room {room_code} created by {username}')


@socketio.on('join-room')
def handle_join_room(data):
    sid = request.sid
    room_code = data['roomCode'].upper()
    username = data['username']
    
    # Check if room exists
    if room_code not in rooms:
        emit('error', 'Room not found. Check the code and try again.')
        return
    
    # Get existing users before adding new one
    existing_users = list(rooms[room_code]['users'].values())
    
    # Add user to room
    rooms[room_code]['users'][sid] = {'username': username, 'socketId': sid}
    user_data[sid] = {'username': username, 'room_code': room_code}
    
    # Join the socket.io room
    join_room(room_code)
    
    # Tell the new user about existing users
    emit('room-joined', {
        'roomCode': room_code,
        'username': username,
        'existingUsers': existing_users
    })
    
    # Tell existing users about the new user
    emit('user-joined', {
        'username': username,
        'socketId': sid
    }, to=room_code, skip_sid=sid)
    
    print(f'{username} joined room {room_code}')


@socketio.on('offer')
def handle_offer(data):
    sid = request.sid
    target_id = data['targetId']
    offer = data['offer']
    
    if sid in user_data:
        emit('offer', {
            'offer': offer,
            'fromId': sid,
            'fromUsername': user_data[sid]['username']
        }, to=target_id)


@socketio.on('answer')
def handle_answer(data):
    sid = request.sid
    target_id = data['targetId']
    answer = data['answer']
    
    emit('answer', {
        'answer': answer,
        'fromId': sid
    }, to=target_id)


@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    sid = request.sid
    target_id = data['targetId']
    candidate = data['candidate']
    
    emit('ice-candidate', {
        'candidate': candidate,
        'fromId': sid
    }, to=target_id)


@socketio.on('leave-room')
def handle_leave_room():
    handle_user_leave(request.sid)


def handle_user_leave(sid):
    if sid not in user_data:
        return
    
    username = user_data[sid]['username']
    room_code = user_data[sid]['room_code']
    
    if room_code and room_code in rooms:
        # Remove user from room
        if sid in rooms[room_code]['users']:
            del rooms[room_code]['users'][sid]
        
        # Notify others
        emit('user-left', {
            'socketId': sid,
            'username': username
        }, to=room_code)
        
        # Leave socket.io room
        leave_room(room_code)
        
        # Delete empty rooms
        if len(rooms[room_code]['users']) == 0:
            del rooms[room_code]
            print(f'Room {room_code} deleted (empty)')
    
    # Clean up user data
    del user_data[sid]


# Need to import request for sid access
from flask_socketio import request

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Rip Chat Server running on port {port}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
