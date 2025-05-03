from flask import Flask, request, jsonify
import os
import sys
import asyncio
import threading
from telethon.sync import TelegramClient
from telethon import events
from telethon.tl.functions.channels import CreateChannelRequest, GetFullChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import InputPeerChannel
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError
from dotenv import load_dotenv
import time
import re
import uuid
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime

# Load environment variables
load_dotenv()

# Print environment variables for debugging
print("="*80)
print("ENVIRONMENT VARIABLES:")
print(f"API_ID: {os.getenv('API_ID')}")
print(f"API_HASH: {'*'*len(os.getenv('API_HASH', '')) if os.getenv('API_HASH') else 'Not set'}")
print(f"PHONE_NUMBER: {os.getenv('PHONE_NUMBER')}")
print(f"DB_NAME: {os.getenv('DB_NAME')}")
print(f"DB_USER: {os.getenv('DB_USER')}")
print(f"DB_HOST: {os.getenv('DB_HOST')}")
print(f"DB_PORT: {os.getenv('DB_PORT')}")
print("="*80)

# PostgreSQL connection parameters
DB_PARAMS = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT')
}

def get_db_connection():
    """Create a database connection"""
    try:
        print(f"Connecting to database: {DB_PARAMS['dbname']} at {DB_PARAMS['host']}:{DB_PARAMS['port']} as {DB_PARAMS['user']}")
        connection = psycopg2.connect(**DB_PARAMS)
        print("Database connection successful")
        return connection
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

def update_session_status_in_db(is_active):
    """Update the is_session_active status in the database."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            # Update the session status
            cur.execute(
                """
                UPDATE "test-telegram-python-user"
                SET is_session_active = %s
                WHERE telegram_id = (SELECT telegram_id FROM "test-telegram-python-user" LIMIT 1)
                """,
                (is_active,)
            )

            conn.commit()
            print(f"Session status updated to: {is_active}")
        except Exception as e:
            print(f"SQL Error updating session status: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Error in update_session_status_in_db: {e}")
        raise

async def check_session_status():
    """Check the is_session_active status from the database."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)

        try:
            # Query the session status
            cur.execute(
                """
                SELECT is_session_active FROM "test-telegram-python-user"
                LIMIT 1
                """
            )

            result = cur.fetchone()
            return result['is_session_active'] if result else False
        except Exception as e:
            print(f"SQL Error checking session status: {e}")
            raise
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Error in check_session_status: {e}")
        raise

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Initialize Flask app
app = Flask(__name__)

# Client session name
SESSION_NAME = 'telegram_session'

# Global variables for message listener
message_listener_client = None
active_listeners = {}  # Dictionary to track active listeners: {group_id: callback_url}
listener_running = False
message_history = {}  # Dictionary to store message history: {group_id: [messages]}

# Dictionary to store group information: {group_name: {"id": unique_id, "channel": channel}}
group_registry = {}

async def create_client_for_request():
    """Create a new client for each request."""
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        # Check session status from the database
        is_active = await check_session_status()
        if is_active:
            print("Session is active in the database, but the client is not authorized.")
        else:
            print("You need to authorize the Telegram client first.")
            print("Run the telegram_group_inviter.py script to authenticate.")
            await client.disconnect()
            return None

    # Update session status to active in the database
    update_session_status_in_db(True)
    return client

async def create_telegram_group(client, group_name, group_description):
    """
    Create a new Telegram group (supergroup/channel) with the given name and description.
    If a group with the same name already exists, return the existing group.
    """
    try:
        # Check if the group already exists in the registry
        if group_name in group_registry:
            existing_group = group_registry[group_name]
            return existing_group["channel"], None, existing_group["id"]

        # Create a supergroup (channel)
        result = await client(CreateChannelRequest(
            title=group_name,
            about=group_description,
            megagroup=True  # Set to True for supergroups
        ))

        channel = result.chats[0]

        # Generate a unique ID for the group
        unique_id = str(uuid.uuid4())

        # Store the group in the registry
        group_registry[group_name] = {"id": unique_id, "channel": channel}

        return channel, None, unique_id
    except Exception as e:
        error_msg = f"Error creating group: {e}"
        return None, error_msg, None

async def get_invite_link(client, channel):
    """
    Generate an invite link for the given channel/group
    """
    try:
        # First approach: Try to get existing invite link
        try:
            full_channel = await client(GetFullChannelRequest(channel))
            if hasattr(full_channel.full_chat, 'invite_link') and full_channel.full_chat.invite_link:
                return full_channel.full_chat.invite_link, None
        except Exception as e:
            print(f"Could not get existing invite link: {e}")
        
        # Second approach: Try to create a new invite link
        try:
            # Create an invite link directly using the client method
            link = await client.export_chat_invite_link(channel.id)
            if link:
                return link, None
        except Exception as e:
            print(f"Could not create invite link with client method: {e}")
        
        # Third approach: Try using the ExportChatInviteRequest
        try:
            # First convert channel to InputPeerChannel
            input_peer = InputPeerChannel(channel.id, channel.access_hash)
            result = await client(ExportChatInviteRequest(peer=input_peer))
            if result and hasattr(result, 'link'):
                return result.link, None
        except Exception as e:
            print(f"Could not create invite link with ExportChatInviteRequest: {e}")
        
        # If all methods fail
        error_msg = "Could not generate invite link after trying multiple methods"
        return None, error_msg
    except Exception as e:
        error_msg = f"Error generating invite link: {e}"
        return None, error_msg

async def send_invites_to_phone_numbers(client, phone_numbers, invite_link, message_text):
    """
    Send invitation messages with the invite link to a list of phone numbers
    """
    results = []
    
    for phone in phone_numbers:
        try:
            # Try to find the user by phone number
            try:
                user = await client.get_entity(phone)
                
                # Send message with invite link
                await client.send_message(
                    user,
                    f"{message_text}\n\n{invite_link}"
                )
                
                results.append({
                    "phone": phone,
                    "status": "success",
                    "message": "Invitation sent successfully"
                })
                
                # Sleep to avoid hitting rate limits
                time.sleep(1)
                
            except Exception as e:
                results.append({
                    "phone": phone,
                    "status": "error",
                    "message": f"Could not find user: {str(e)}"
                })
                
        except PeerFloodError:
            results.append({
                "phone": phone,
                "status": "error",
                "message": "Telegram flood error. Try again later."
            })
        except UserPrivacyRestrictedError:
            results.append({
                "phone": phone,
                "status": "error",
                "message": "User has privacy restrictions"
            })
        except Exception as e:
            results.append({
                "phone": phone,
                "status": "error",
                "message": str(e)
            })
    
    return results

async def extract_group_entity_from_link(client, invite_link):
    """
    Extract group entity from invite link
    """
    try:
        # Join the group using the invite link if not already a member
        try:
            # Extract the group username or hash from the link
            if 't.me/' in invite_link:
                if '+' in invite_link:
                    # This is a private group invite link (e.g., https://t.me/+abcdef123456)
                    # We need to join the group first
                    group_entity = await client.get_entity(invite_link)
                    await client(JoinChannelRequest(group_entity))
                else:
                    # This is a public group/channel (e.g., https://t.me/groupname)
                    username = invite_link.split('t.me/')[1].strip('/')
                    group_entity = await client.get_entity(username)
            else:
                return None, "Invalid invite link format"
                
            return group_entity, None
        except Exception as e:
            error_msg = f"Error joining group: {e}"
            return None, error_msg
    except Exception as e:
        error_msg = f"Error extracting group from link: {e}"
        return None, error_msg

async def send_message_as_user_to_group(client, group_entity, sender_name, sender_phone, message_text):
    """
    Send a message to a group that appears to be from another user
    """
    try:
        # Format message to appear from the user
        formatted_message = f"📱 **Mesaj: {sender_name} ({sender_phone})** 📱\n\n{message_text}"
        
        # Send the formatted message
        sent_message = await client.send_message(group_entity, formatted_message)
        
        # Get the sender (our client user)
        me = await client.get_me()
        
        # Save sender information to database
        try:
            await save_user_to_db(me)
            print(f"Outgoing user saved to database: {me.id}")
        except Exception as e:
            print(f"Error saving outgoing user to database: {e}")
        
        # Save message to database as outgoing
        try:
            await save_message_to_db(sent_message, group_entity.id, me.id, is_outgoing=True)
            print(f"Outgoing message saved to database: {sent_message.id}")
        except Exception as e:
            print(f"Error saving outgoing message to database: {e}")
        
        return True, None
    except Exception as e:
        error_msg = f"Error sending message to group: {e}"
        return False, error_msg

async def start_message_listener():
    """
    Start a background client that listens for messages in groups
    """
    global message_listener_client
    global listener_running
    
    # Only start if not already running
    if listener_running:
        print("Message listener is already running")
        return True
    
    try:
        print("Creating listener session...")
        # Use a completely different session name for the listener
        listener_session = f"{SESSION_NAME}_listener_separate"
        
        # Initialize the message listener client with a separate session
        message_listener_client = TelegramClient(listener_session, API_ID, API_HASH)
        
        print(f"Connecting to Telegram with API_ID: {API_ID}, SESSION: {listener_session}")
        await message_listener_client.connect()
        
        if not await message_listener_client.is_user_authorized():
            print("Listener client needs authorization. Starting authorization process...")
            # Copy auth from main session
            try:
                # First try to log in using the phone number from .env
                print(f"Logging in with phone number: {PHONE_NUMBER}")
                await message_listener_client.start(phone=PHONE_NUMBER)
                print("Listener client authorized successfully!")
            except Exception as e:
                print(f"Failed to authorize listener client: {e}")
                return False
        else:
            print("Listener client already authorized")
        
        # Get information about the connected user
        me = await message_listener_client.get_me()
        print(f"Connected as: {me.first_name} {me.last_name if me.last_name else ''} (@{me.username if me.username else 'no_username'})")
        
        # Register the message handler for incoming messages
        @message_listener_client.on(events.NewMessage())
        async def message_handler(event):
            """Handle new messages in any chat"""
            try:
                # Get message details
                message = event.message
                chat = await event.get_chat()
                chat_id = chat.id
                sender = await event.get_sender()
                
                # Save user information to database
                try:
                    await save_user_to_db(sender)
                    print(f"User saved to database: {sender.id}")
                except Exception as e:
                    print(f"Error saving user to database: {e}")
                
                # Save message to database (incoming message)
                try:
                    await save_message_to_db(message, chat_id, sender.id, is_outgoing=False)
                    print(f"Message saved to database: {message.id}")
                except Exception as e:
                    print(f"Error saving message to database: {e}")
                
                # Extract sender info for message history
                sender_info = {
                    "id": sender.id,
                    "first_name": getattr(sender, 'first_name', None),
                    "last_name": getattr(sender, 'last_name', None),
                    "username": getattr(sender, 'username', None),
                    "phone": getattr(sender, 'phone', None)
                }
                
                # Create message info
                message_info = {
                    "id": message.id,
                    "text": message.text,
                    "date": message.date.isoformat(),
                    "sender": sender_info
                }
                
                # Add to message history
                if chat_id not in message_history:
                    message_history[chat_id] = []
                
                message_history[chat_id].append(message_info)
                
                # Keep only the last 100 messages in memory
                if len(message_history[chat_id]) > 100:
                    message_history[chat_id] = message_history[chat_id][-100:]
                
                # Format sender name for console output
                sender_name = f"{sender_info['first_name'] or ''} {sender_info['last_name'] or ''}".strip()
                if not sender_name and sender_info['username']:
                    sender_name = f"@{sender_info['username']}"
                if not sender_name:
                    sender_name = f"ID: {sender_info['id']}"
                
                # Print detailed message info to console
                print("\n" + "="*50)
                print(f"💬 YENİ MESAJ ALINDI: {chat.title}")
                print(f"📅 Tarih: {message.date.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"👤 Gönderen: {sender_name}")
                if sender_info['username']:
                    print(f"🔖 Kullanıcı Adı: @{sender_info['username']}")
                print(f"🆔 Kullanıcı ID: {sender_info['id']}")
                if sender_info['phone']:
                    print(f"📱 Telefon: {sender_info['phone']}")
                print(f"📝 Mesaj: {message.text}")
                
                # If message has media, show that as well
                if message.media:
                    print(f"📷 Medya: {type(message.media).__name__}")
                
                # If message is a reply to another message
                if message.reply_to:
                    print(f"↩️ Yanıt Verilen Mesaj ID: {message.reply_to.reply_to_msg_id}")
                
                print("="*50 + "\n")
            except Exception as e:
                print(f"Error in message handler: {e}")
        
        # Start the client
        print("Setting listener running status to True")
        listener_running = True
        print("Message listener started successfully")
        return True
        
    except Exception as e:
        print(f"Error starting message listener: {e}")
        if message_listener_client:
            await message_listener_client.disconnect()
            message_listener_client = None
        listener_running = False
        return False

async def stop_message_listener():
    """
    Stop the message listener client
    """
    global message_listener_client
    global listener_running
    
    if message_listener_client and listener_running:
        await message_listener_client.disconnect()
        message_listener_client = None
        listener_running = False
        print("Message listener stopped")
        return True
    
    return False

async def add_group_to_listeners(group_link):
    """
    Add a group to the active listeners
    """
    global active_listeners
    
    # Create a temporary client to get the group entity
    client = await create_client_for_request()
    if not client:
        return None, "Failed to initialize client"
    
    try:
        # Get the group entity
        group_entity, error = await extract_group_entity_from_link(client, group_link)
        if error:
            await client.disconnect()
            return None, error
        
        # Add to active listeners
        group_id = group_entity.id
        active_listeners[group_id] = group_link
        
        # Initialize message history for this group
        if group_id not in message_history:
            message_history[group_id] = []
        
        await client.disconnect()
        return group_entity, None
    except Exception as e:
        await client.disconnect()
        return None, f"Error adding group to listeners: {e}"

def run_listener_in_background():
    """
    Run the message listener in a background thread
    """
    async def _run_listener():
        try:
            print("Starting message listener...")
            success = await start_message_listener()
            if success:
                print("Message listener started successfully in background thread")
                # Keep the client running indefinitely
                while listener_running:
                    await asyncio.sleep(1)
            else:
                print("Failed to start message listener")
        except Exception as e:
            print(f"Error in _run_listener: {e}")
    
    # Run in a new thread
    def _thread_target():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run_listener())
        except Exception as e:
            print(f"Exception in thread target: {e}")
    
    print("Creating background thread for listener...")
    thread = threading.Thread(target=_thread_target)
    thread.daemon = True  # Thread will exit when the main program exits
    thread.start()
    print(f"Background thread started with ID: {thread.ident}")
    return thread

@app.route('/create-telegram-group', methods=['POST'])
def create_group():
    """
    API endpoint to create a Telegram group and invite users
    
    Expected JSON input:
    {
        "group_name": "Group Name",
        "group_description": "Group Description",
        "phones": ["+905551112233", "+905551112244"],
        "invite_message": "You are invited to join our group!"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_name' not in data:
        return jsonify({"error": "group_name is required"}), 400
    
    if 'phones' not in data or not isinstance(data['phones'], list):
        return jsonify({"error": "phones list is required"}), 400
    
    # Extract data
    group_name = data['group_name']
    group_description = data.get('group_description', f"Group created via API: {group_name}")
    phones = data['phones']
    invite_message = data.get('invite_message', f"You are invited to join the group: {group_name}")
    
    # Create async function to handle the process
    async def process_request():
        # Create a new client for this request
        client = await create_client_for_request()
        if client is None:
            return {"error": "Failed to initialize Telegram client"}, 500
        
        try:
            # Create the group
            channel, error, unique_id = await create_telegram_group(client, group_name, group_description)
            
            if error:
                return {"error": error}, 500
            
            # Generate invite link
            invite_link, error = await get_invite_link(client, channel)
            
            if error:
                return {"error": error}, 500
            
            # Send invites
            invite_results = await send_invites_to_phone_numbers(client, phones, invite_link, invite_message)
            
            # Return the result
            return {
                "success": True,
                "group": {
                    "name": group_name,
                    "id": unique_id,
                    "invite_link": invite_link
                },
                "invitations": invite_results
            }, 200
        finally:
            # Always disconnect the client when done
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/send-telegram-group-message', methods=['POST'])
def send_group_message():
    """
    API endpoint to send a message to a Telegram group
    
    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456",
        "sender_name": "John Doe",
        "sender_phone": "+905551112233",
        "message": "Hello, this is a test message!"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400
    
    if 'sender_name' not in data:
        return jsonify({"error": "sender_name is required"}), 400
    
    if 'sender_phone' not in data:
        return jsonify({"error": "sender_phone is required"}), 400
    
    if 'message' not in data:
        return jsonify({"error": "message is required"}), 400
    
    # Extract data
    group_link = data['group_link']
    sender_name = data['sender_name']
    sender_phone = data['sender_phone']
    message = data['message']
    
    # Create async function to handle the process
    async def process_request():
        # Create a new client for this request
        client = await create_client_for_request()
        if client is None:
            return {"error": "Failed to initialize Telegram client"}, 500
        
        try:
            # Get group entity from link
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            
            if error:
                return {"error": error}, 500
            
            # Send message
            success, error = await send_message_as_user_to_group(client, group_entity, sender_name, sender_phone, message)
            
            if error:
                return {"error": error}, 500
            
            # Return the result
            return {
                "success": True,
                "group_link": group_link,
                "message": "Message sent successfully"
            }, 200
        finally:
            # Always disconnect the client when done
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/listen-to-group', methods=['POST'])
def listen_to_group():
    """
    API endpoint to start listening to messages in a Telegram group
    
    Expected JSON input:
    {
        "group_links": ["https://t.me/+abcdef123456", "https://t.me/groupname"]
    }
    
    You can also provide a single group link:
    {
        "group_link": "https://t.me/+abcdef123456"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    group_links = []
    
    # Handle both single group_link and multiple group_links
    if 'group_link' in data:
        group_links.append(data['group_link'])
    elif 'group_links' in data and isinstance(data['group_links'], list):
        group_links = data['group_links']
    else:
        return jsonify({"error": "Either group_link or group_links (array) is required"}), 400
    
    if not group_links:
        return jsonify({"error": "No valid group links provided"}), 400
    
    # Create async function to handle the process
    async def process_request():
        # Make sure the listener is running
        global listener_running
        
        try:
            if not listener_running:
                # Start the listener in a background thread
                print("Starting message listener in background...")
                thread = run_listener_in_background()
                # Wait for the listener to start
                for _ in range(10):  # Wait up to 10 seconds
                    if listener_running:
                        print("Listener started successfully!")
                        break
                    print("Waiting for listener to start...")
                    await asyncio.sleep(1)
            
            if not listener_running:
                error_message = "Failed to start message listener. Check console for details."
                print(f"ERROR: {error_message}")
                return {"error": error_message}, 500
            
            results = []
            errors = []
            
            # Add each group to the listeners
            for group_link in group_links:
                try:
                    print(f"Adding group to listeners: {group_link}")
                    group_entity, error = await add_group_to_listeners(group_link)
                    
                    if error:
                        print(f"Error adding group: {error}")
                        errors.append({
                            "group_link": group_link,
                            "error": error
                        })
                    else:
                        print(f"Successfully added group: {group_entity.title}")
                        results.append({
                            "id": group_entity.id,
                            "title": group_entity.title,
                            "link": group_link
                        })
                except Exception as e:
                    print(f"Exception adding group {group_link}: {e}")
                    errors.append({
                        "group_link": group_link,
                        "error": str(e)
                    })
            
            # Return the result
            return {
                "success": len(results) > 0,
                "groups": results,
                "errors": errors,
                "message": f"Now listening to {len(results)} group(s)" if results else "Failed to listen to any groups"
            }, 200 if results else 500
        except Exception as e:
            print(f"Exception in process_request: {e}")
            return {"error": f"Failed to process request: {str(e)}"}, 500
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result, status_code = loop.run_until_complete(process_request())
    except Exception as e:
        print(f"Exception running process_request: {e}")
        result = {"error": f"Exception: {str(e)}"}
        status_code = 500
    finally:
        loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/get-group-messages', methods=['POST'])
def get_group_messages():
    """
    API endpoint to get messages from a Telegram group
    
    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400
    
    group_link = data['group_link']
    
    # Create async function to handle the process
    async def process_request():
        # Create a temporary client
        client = await create_client_for_request()
        if not client:
            return {"error": "Failed to initialize client"}, 500
        
        try:
            # Get the group entity
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            if error:
                return {"error": error}, 500
            
            # Check if we're listening to this group
            group_id = group_entity.id
            if group_id not in active_listeners:
                # Add it to listeners if not already listening
                await add_group_to_listeners(group_link)
                return {
                    "success": True,
                    "group": {
                        "id": group_id,
                        "title": group_entity.title,
                        "link": group_link
                    },
                    "messages": [],
                    "message": "Started listening to group, no messages yet"
                }, 200
            
            # Get messages for this group
            messages = message_history.get(group_id, [])
            
            # Return the result
            return {
                "success": True,
                "group": {
                    "id": group_id,
                    "title": group_entity.title,
                    "link": group_link
                },
                "messages": messages
            }, 200
        finally:
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/stop-listening', methods=['POST'])
def stop_listening():
    """
    API endpoint to stop listening to messages in a Telegram group
    
    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400
    
    group_link = data['group_link']
    
    # Create async function to handle the process
    async def process_request():
        # Create a temporary client
        client = await create_client_for_request()
        if not client:
            return {"error": "Failed to initialize client"}, 500
        
        try:
            # Get the group entity
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            if error:
                return {"error": error}, 500
            
            # Check if we're listening to this group
            group_id = group_entity.id
            if group_id in active_listeners:
                # Remove from active listeners
                del active_listeners[group_id]
                
                # Clear message history for this group
                if group_id in message_history:
                    del message_history[group_id]
                
                # If no more active listeners, stop the listener
                if not active_listeners and listener_running:
                    await stop_message_listener()
                
                return {
                    "success": True,
                    "message": f"Stopped listening to group: {group_entity.title}"
                }, 200
            else:
                return {
                    "success": False,
                    "message": "Not listening to this group"
                }, 400
        finally:
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/invite-to-telegram-group', methods=['POST'])
def invite_to_group():
    """
    API endpoint to invite users to a Telegram group via direct message

    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456",
        "phones": ["+905551112233", "+905551112244"],
        "invite_message": "You are invited to join our group!"
    }
    """
    # Get request data
    data = request.json

    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400

    if 'phones' not in data or not isinstance(data['phones'], list):
        return jsonify({"error": "phones list is required"}), 400

    # Extract data
    group_link = data['group_link']
    phones = data['phones']
    invite_message = data.get('invite_message', "You are invited to join our group!")

    # Create async function to handle the process
    async def process_request():
        # Create a new client for this request
        client = await create_client_for_request()
        if client is None:
            return {"error": "Failed to initialize Telegram client"}, 500

        try:
            # Get group entity from link
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            if error:
                return {"error": error}, 500

            # Generate invite link
            invite_link, error = await get_invite_link(client, group_entity)
            if error:
                return {"error": error}, 500

            # Send invites
            invite_results = await send_invites_to_phone_numbers(client, phones, invite_link, invite_message)

            # Return the result
            return {
                "success": True,
                "group": {
                    "id": group_entity.id,
                    "title": group_entity.title,
                    "link": group_link
                },
                "invitations": invite_results
            }, 200
        finally:
            # Always disconnect the client when done
            await client.disconnect()

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()

    # Return the result
    return jsonify(result), status_code

async def save_user_to_db(sender):
    """Save or update user information in the database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            # Check if user exists
            cur.execute("""
                SELECT telegram_id FROM "test-telegram-python-user"
                WHERE telegram_id = %s
            """, (sender.id,))
            
            existing_user = cur.fetchone()
            
            if existing_user is None:
                # Insert new user
                print(f"Inserting new user with telegram_id={sender.id}")
                cur.execute("""
                    INSERT INTO "test-telegram-python-user" 
                    (telegram_id, first_name, last_name, username, phone)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    sender.id,
                    getattr(sender, 'first_name', None),
                    getattr(sender, 'last_name', None),
                    getattr(sender, 'username', None),
                    getattr(sender, 'phone', None)
                ))
            else:
                # Update existing user
                print(f"Updating user with telegram_id={sender.id}")
                cur.execute("""
                    UPDATE "test-telegram-python-user"
                    SET first_name = %s, last_name = %s, username = %s, phone = %s
                    WHERE telegram_id = %s
                """, (
                    getattr(sender, 'first_name', None),
                    getattr(sender, 'last_name', None),
                    getattr(sender, 'username', None),
                    getattr(sender, 'phone', None),
                    sender.id
                ))
            
            conn.commit()
            print(f"User saved/updated in database: ID={sender.id}")
        except Exception as e:
            print(f"SQL Error saving user to database: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Error in save_user_to_db: {e}")
        raise

async def save_message_to_db(message, chat_id, sender_id, is_outgoing=False):
    """Save message information in the database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            print(f"Saving message to database: ID={message.id}, chat_id={chat_id}, sender_id={sender_id}")
            cur.execute("""
                INSERT INTO "test-telegram-python-messages"
                (group_id, message_id, sender_id, message_text, message_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                chat_id,
                message.id,
                sender_id,
                message.text,
                message.date
            ))
            
            conn.commit()
            print(f"Message saved to database: ID={message.id}, Text={message.text}")
        except Exception as e:
            print(f"SQL Error saving message to database: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Error in save_message_to_db: {e}")
        raise

# Initialize the message listener when the app starts
if __name__ == '__main__':
    # Start the message listener in a background thread
    run_listener_in_background()
    
    # Run Flask app
    app.run(debug=True, port=5000)