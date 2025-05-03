import os
import asyncio
from telethon.sync import TelegramClient
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import DictCursor

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# PostgreSQL connection parameters
DB_PARAMS = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT')
}

# Session name
SESSION_NAME = 'telegram_session'

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

def update_session_status_in_db(telegram_id, is_active=True):
    """Update the is_session_active status in the database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            # First check if user exists
            cur.execute("""
                SELECT telegram_id FROM "test-telegram-python-user"
                WHERE telegram_id = %s
            """, (telegram_id,))
            
            if cur.fetchone() is None:
                # Insert new user if not exists
                cur.execute("""
                    INSERT INTO "test-telegram-python-user" 
                    (telegram_id, is_session_active)
                    VALUES (%s, %s)
                """, (telegram_id, is_active))
            else:
                # Update existing user
                cur.execute("""
                    UPDATE "test-telegram-python-user"
                    SET is_session_active = %s
                    WHERE telegram_id = %s
                """, (is_active, telegram_id))
            
            conn.commit()
            print(f"Session status updated to {is_active} for user {telegram_id}")
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

async def authenticate():
    """Authenticate the Telegram client and create session file"""
    print(f"API_ID: {API_ID}")
    print(f"API_HASH: {API_HASH}")
    print(f"PHONE_NUMBER: {PHONE_NUMBER}")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Need to login...")
        # Send code (automatically sends to PHONE_NUMBER)
        await client.send_code_request(PHONE_NUMBER)
        
        # Ask for the code that Telegram sent
        verification_code = input("Enter the verification code you received: ")
        
        try:
            # Try to sign in with the provided code
            await client.sign_in(PHONE_NUMBER, verification_code)
            print("Successfully logged in!")
            
            # Get user info and update session status
            me = await client.get_me()
            update_session_status_in_db(me.id, True)
            
        except Exception as e:
            print(f"Error signing in: {e}")
            
            # Check if two-factor authentication is enabled
            if "2FA" in str(e) or "password" in str(e).lower():
                password = input("Enter your two-factor authentication password: ")
                await client.sign_in(password=password)
                print("Successfully logged in with 2FA!")
                
                # Get user info and update session status after 2FA
                me = await client.get_me()
                update_session_status_in_db(me.id, True)
    else:
        print("Already authenticated!")
        # Update session status for already authenticated user
        me = await client.get_me()
        update_session_status_in_db(me.id, True)
        
    # Get and display some account info
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (ID: {me.id})")
    
    # Create listener session by copying the main session
    # Use same auth credentials for listener
    listener_client = TelegramClient(f"{SESSION_NAME}_listener", API_ID, API_HASH)
    await listener_client.connect()
    
    if not await listener_client.is_user_authorized():
        # Copy auth credentials from main session to listener session
        await listener_client.sign_in(phone=PHONE_NUMBER)
        print("Listener session authenticated!")
    else:
        print("Listener session already authenticated!")
    
    # Close connections
    await listener_client.disconnect()
    await client.disconnect()
    
    return True

if __name__ == "__main__":
    # Run the authentication
    loop = asyncio.get_event_loop()
    loop.run_until_complete(authenticate())
    
    print("\nAuthentication complete! You can now run the main API.")
    print("Run: python telegram_api.py")