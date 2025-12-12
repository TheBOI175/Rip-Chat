from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import os
import time
from threading import RLock

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rip-chat-secret-key'

socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=20, ping_interval=10)

# Thread lock for data safety (RLock allows same thread to acquire multiple times)
data_lock = RLock()

# Data structures
rooms = {}  # { room_code: { users: {}, created_at: timestamp, last_activity: timestamp } }
user_data = {}  # { sid: { username, room_code, joined_at } }
rate_limits = {}  # { sid: { last_action: timestamp, action_count: int } }

# Configuration
MAX_USERS_PER_ROOM = 10
MAX_ROOMS = 1000
MAX_USERNAME_LENGTH = 20
MIN_USERNAME_LENGTH = 1
RATE_LIMIT_WINDOW = 5  # seconds
RATE_LIMIT_MAX_ACTIONS = 10  # max actions per window
ROOM_INACTIVE_TIMEOUT = 3600  # 1 hour - cleanup inactive rooms
ALLOWED_USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")


def log(message):
    """Timestamped logging"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{timestamp}] {message}')


def generate_room_code():
    """Generate unique 6-character room code"""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    for _ in range(100):  # Max attempts
        code = ''.join(random.choice(chars) for _ in range(6))
        if code not in rooms:
            return code
    return None  # Failed to generate unique code


def sanitize_username(username):
    """Clean and validate username"""
    if not username or not isinstance(username, str):
        return None, "Username is required"
    
    # Strip whitespace
    username = username.strip()
    
    # Check length
    if len(username) < MIN_USERNAME_LENGTH:
        return None, "Username is too short"
    
    if len(username) > MAX_USERNAME_LENGTH:
        username = username[:MAX_USERNAME_LENGTH]
    
    # Check for valid characters
    if not all(c in ALLOWED_USERNAME_CHARS for c in username):
        return None, "Username contains invalid characters"
    
    # Check if it's just whitespace
    if not username.replace(" ", ""):
        return None, "Username cannot be only spaces"
    
    return username, None


def is_username_taken(room_code, username, exclude_sid=None):
    """Check if username is already taken in room"""
    if room_code not in rooms:
        return False
    
    for sid, user in rooms[room_code]['users'].items():
        if sid != exclude_sid and user['username'].lower() == username.lower():
            return True
    return False


def check_rate_limit(sid):
    """Check if user is rate limited. Returns (is_limited, message)"""
    current_time = time.time()
    
    if sid not in rate_limits:
        rate_limits[sid] = {'last_action': current_time, 'action_count': 1}
        return False, None
    
    user_rate = rate_limits[sid]
    
    # Reset if outside window
    if current_time - user_rate['last_action'] > RATE_LIMIT_WINDOW:
        rate_limits[sid] = {'last_action': current_time, 'action_count': 1}
        return False, None
    
    # Increment and check
    user_rate['action_count'] += 1
    user_rate['last_action'] = current_time
    
    if user_rate['action_count'] > RATE_LIMIT_MAX_ACTIONS:
        return True, "Too many actions. Please slow down."
    
    return False, None


def cleanup_rate_limits():
    """Remove old rate limit entries"""
    current_time = time.time()
    to_remove = [sid for sid, data in rate_limits.items() 
                 if current_time - data['last_action'] > RATE_LIMIT_WINDOW * 2]
    for sid in to_remove:
        del rate_limits[sid]


def cleanup_inactive_rooms():
    """Remove rooms that have been inactive"""
    current_time = time.time()
    to_remove = []
    
    for room_code, room in rooms.items():
        # Remove if empty
        if len(room['users']) == 0:
            to_remove.append(room_code)
        # Remove if inactive for too long
        elif current_time - room['last_activity'] > ROOM_INACTIVE_TIMEOUT:
            to_remove.append(room_code)
    
    for room_code in to_remove:
        del rooms[room_code]
        log(f'Room {room_code} cleaned up (empty or inactive)')


def update_room_activity(room_code):
    """Update last activity timestamp for room"""
    if room_code in rooms:
        rooms[room_code]['last_activity'] = time.time()


def handle_user_leave(sid, notify=True):
    """Handle user leaving - used by disconnect and leave-room"""
    with data_lock:
        if sid not in user_data:
            return
        
        username = user_data[sid]['username']
        room_code = user_data[sid]['room_code']
        
        log(f'User leaving: {username} from room {room_code}')
        
        if room_code and room_code in rooms:
            # Remove user from room
            if sid in rooms[room_code]['users']:
                del rooms[room_code]['users'][sid]
            
            # Notify others if requested
            if notify:
                emit('user-left', {
                    'socketId': sid,
                    'username': username
                }, to=room_code)
            
            # Leave socket.io room
            leave_room(room_code)
            
            # Update activity or delete if empty
            if len(rooms[room_code]['users']) == 0:
                del rooms[room_code]
                log(f'Room {room_code} deleted (empty)')
            else:
                update_room_activity(room_code)
                log(f'Room {room_code} now has {len(rooms[room_code]["users"])} user(s)')
        
        # Clean up user data
        del user_data[sid]
        
        # Clean up rate limits
        if sid in rate_limits:
            del rate_limits[sid]


def get_room_info(room_code):
    """Get room info for status updates"""
    if room_code not in rooms:
        return None
    
    room = rooms[room_code]
    return {
        'code': room_code,
        'userCount': len(room['users']),
        'users': [{'username': u['username'], 'muted': u['muted']} 
                  for u in room['users'].values()]
    }


# ==================== SOCKET EVENTS ====================

@socketio.on('connect')
def handle_connect():
    log(f'User connected: {request.sid}')
    # Periodic cleanup on new connections
    cleanup_inactive_rooms()
    cleanup_rate_limits()


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    log(f'User disconnected: {sid}')
    handle_user_leave(sid, notify=True)


@socketio.on('create-room')
def handle_create_room(username):
    sid = request.sid
    
    # Rate limit check
    is_limited, limit_msg = check_rate_limit(sid)
    if is_limited:
        emit('error', limit_msg)
        return
    
    # Validate username
    username, error = sanitize_username(username)
    if error:
        emit('error', error)
        return
    
    with data_lock:
        # Check max rooms
        if len(rooms) >= MAX_ROOMS:
            emit('error', 'Server is full. Please try again later.')
            return
        
        # Leave current room if in one
        if sid in user_data:
            handle_user_leave(sid, notify=True)
        
        # Generate room code
        room_code = generate_room_code()
        if not room_code:
            emit('error', 'Could not create room. Please try again.')
            return
        
        current_time = time.time()
        
        # Create room
        rooms[room_code] = {
            'users': {
                sid: {
                    'username': username,
                    'socketId': sid,
                    'muted': False
                }
            },
            'created_at': current_time,
            'last_activity': current_time
        }
        
        # Track user
        user_data[sid] = {
            'username': username,
            'room_code': room_code,
            'joined_at': current_time
        }
        
        join_room(room_code)
        
        emit('room-created', {
            'roomCode': room_code,
            'username': username
        })
        
        log(f'Room {room_code} created by {username}')


@socketio.on('join-room')
def handle_join_room(data):
    sid = request.sid
    
    # Rate limit check
    is_limited, limit_msg = check_rate_limit(sid)
    if is_limited:
        emit('error', limit_msg)
        return
    
    # Validate input
    if not data or not isinstance(data, dict):
        emit('error', 'Invalid request')
        return
    
    room_code = data.get('roomCode', '')
    username = data.get('username', '')
    
    # Validate room code
    if not room_code or not isinstance(room_code, str):
        emit('error', 'Room code is required')
        return
    
    room_code = room_code.upper().strip()
    
    if len(room_code) != 6:
        emit('error', 'Invalid room code format')
        return
    
    # Validate username
    username, error = sanitize_username(username)
    if error:
        emit('error', error)
        return
    
    with data_lock:
        # Check room exists
        if room_code not in rooms:
            emit('error', 'Room not found. Check the code and try again.')
            return
        
        room = rooms[room_code]
        
        # Check room capacity
        if len(room['users']) >= MAX_USERS_PER_ROOM:
            emit('error', f'Room is full (max {MAX_USERS_PER_ROOM} users).')
            return
        
        # Check duplicate username (case-insensitive)
        if is_username_taken(room_code, username, exclude_sid=sid):
            emit('error', f'Username "{username}" is already taken in this room.')
            return
        
        # Leave current room if in one
        if sid in user_data:
            handle_user_leave(sid, notify=True)
        
        current_time = time.time()
        
        # Get existing users before adding
        existing_users = list(room['users'].values())
        
        # Add user to room
        room['users'][sid] = {
            'username': username,
            'socketId': sid,
            'muted': False
        }
        room['last_activity'] = current_time
        
        # Track user
        user_data[sid] = {
            'username': username,
            'room_code': room_code,
            'joined_at': current_time
        }
        
        join_room(room_code)
        
        # Tell new user about existing users
        emit('room-joined', {
            'roomCode': room_code,
            'username': username,
            'existingUsers': existing_users
        })
        
        # Tell existing users about new user
        emit('user-joined', {
            'username': username,
            'socketId': sid,
            'muted': False
        }, to=room_code, skip_sid=sid)
        
        log(f'{username} joined room {room_code} ({len(room["users"])} users)')


@socketio.on('leave-room')
def handle_leave_room():
    sid = request.sid
    
    # Rate limit check
    is_limited, limit_msg = check_rate_limit(sid)
    if is_limited:
        emit('error', limit_msg)
        return
    
    handle_user_leave(sid, notify=True)
    emit('left-room', {'success': True})


@socketio.on('mute-status')
def handle_mute_status(data):
    sid = request.sid
    
    if not data or not isinstance(data, dict):
        return
    
    muted = bool(data.get('muted', False))
    
    with data_lock:
        if sid not in user_data:
            return
        
        room_code = user_data[sid]['room_code']
        
        if room_code and room_code in rooms:
            room = rooms[room_code]
            
            if sid in room['users']:
                room['users'][sid]['muted'] = muted
                update_room_activity(room_code)
                
                # Broadcast to everyone in room
                emit('user-mute-changed', {
                    'socketId': sid,
                    'muted': muted
                }, to=room_code)


@socketio.on('offer')
def handle_offer(data):
    sid = request.sid
    
    if not data or not isinstance(data, dict):
        return
    
    target_id = data.get('targetId')
    offer = data.get('offer')
    
    if not target_id or not offer:
        return
    
    # Verify sender is in a room
    if sid not in user_data:
        return
    
    # Verify target exists and is in same room
    if target_id not in user_data:
        return
    
    if user_data[sid]['room_code'] != user_data[target_id]['room_code']:
        return
    
    emit('offer', {
        'offer': offer,
        'fromId': sid,
        'fromUsername': user_data[sid]['username']
    }, to=target_id)


@socketio.on('answer')
def handle_answer(data):
    sid = request.sid
    
    if not data or not isinstance(data, dict):
        return
    
    target_id = data.get('targetId')
    answer = data.get('answer')
    
    if not target_id or not answer:
        return
    
    # Verify sender is in a room
    if sid not in user_data:
        return
    
    # Verify target exists and is in same room
    if target_id not in user_data:
        return
    
    if user_data[sid]['room_code'] != user_data[target_id]['room_code']:
        return
    
    emit('answer', {
        'answer': answer,
        'fromId': sid
    }, to=target_id)


@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    sid = request.sid
    
    if not data or not isinstance(data, dict):
        return
    
    target_id = data.get('targetId')
    candidate = data.get('candidate')
    
    if not target_id:
        return
    
    # Verify sender is in a room
    if sid not in user_data:
        return
    
    # Verify target exists and is in same room
    if target_id not in user_data:
        return
    
    if user_data[sid]['room_code'] != user_data[target_id]['room_code']:
        return
    
    emit('ice-candidate', {
        'candidate': candidate,
        'fromId': sid
    }, to=target_id)


@socketio.on('ping-server')
def handle_ping():
    """Custom ping for connection health check"""
    emit('pong-server', {'timestamp': time.time()})


@socketio.on('get-room-info')
def handle_get_room_info():
    """Get current room info (for reconnection/refresh)"""
    sid = request.sid
    
    if sid not in user_data:
        emit('room-info', {'inRoom': False})
        return
    
    room_code = user_data[sid]['room_code']
    room_info = get_room_info(room_code)
    
    if room_info:
        emit('room-info', {
            'inRoom': True,
            'room': room_info
        })
    else:
        emit('room-info', {'inRoom': False})


# ==================== HTTP ROUTES ====================

@app.route('/')
def index():
    return 'Rip Chat Server Running'


@app.route('/status')
def status():
    return {
        'status': 'online',
        'rooms': len(rooms),
        'users': len(user_data),
        'config': {
            'maxUsersPerRoom': MAX_USERS_PER_ROOM,
            'maxRooms': MAX_ROOMS
        }
    }


@app.route('/health')
def health():
    return {'healthy': True}


# ==================== MAIN ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    log(f'Rip Chat Server running on port {port}')
    log(f'Max users per room: {MAX_USERS_PER_ROOM}')
    log(f'Max rooms: {MAX_ROOMS}')
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
