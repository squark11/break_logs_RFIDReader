from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from datetime import datetime
import sqlite3
import time
import serial
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'

# Login manager setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Hard-coded admin credentials
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin'

# Placeholder for last read time and breaks
last_read_time = {}

# Database configuration
database = 'break_logs.db'  # SQLite database file

# Global lock for serial port access
serial_lock = threading.Lock()

def connect_to_db():
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row  # For easier access to column names
    return conn

def create_db():
    conn = connect_to_db()
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS Users (
        UserID INTEGER PRIMARY KEY AUTOINCREMENT,
        Username TEXT NOT NULL,
        RFIDCode TEXT 
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS Logs (
        LogID INTEGER PRIMARY KEY AUTOINCREMENT,
        UserID INTEGER NOT NULL,
        Action TEXT NOT NULL,
        BreakNumber INTEGER NOT NULL,
        Timestamp TEXT NOT NULL,
        FOREIGN KEY (UserID) REFERENCES Users(UserID)
    )''')

    conn.commit()
    conn.close()

class DummyUser(UserMixin):
    def __init__(self):
        self.id = 1
        self.username = ADMIN_USERNAME

    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

@login_manager.user_loader
def load_user(user_id):
    return DummyUser() if int(user_id) == 1 else None

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            login_user(DummyUser())  # Use a dummy user object
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials, try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

def handle_rfid_data(ser):
    while True:
        with serial_lock:  # Use lock for reading from the port
            if ser.in_waiting > 0:
                raw_data = ser.readline()
                try:
                    rfid_code = raw_data.decode('cp1252').strip()
                    if rfid_code:
                        print(f"RFID Code Read: {rfid_code}")
                        break_number = determine_break_number(rfid_code)
                        action = 'Przerwa ' + str((break_number + 1) // 2) + (' - start' if break_number % 2 == 1 else ' - koniec')
                        log_action(rfid_code, action, break_number)
                except UnicodeDecodeError:
                    print(f"UnicodeDecodeError: {raw_data}")
        time.sleep(0.1)

def determine_break_number(rfid_code):
    conn = connect_to_db()
    cursor = conn.cursor()

    today = datetime.now().date()

    cursor.execute("SELECT MAX(BreakNumber) FROM Logs WHERE UserID = ? AND DATE(Timestamp) = ?",
                   (get_user_id_by_rfid(rfid_code), today))

    max_break_number = cursor.fetchone()[0] or 0
    conn.close()

    return max_break_number + 1

def read_rfid_from_serial():
    with serial_lock:  # Use lock to prevent access conflicts
        ser = serial.Serial('COM7', 9600, timeout=1)
        try:
            while True:
                if ser.in_waiting > 0:  # Check if data is available in the buffer
                    raw_data = ser.readline()
                    try:
                        rfid_code = raw_data.decode('cp1252').strip()
                        if rfid_code:
                            print(f"RFID Code Read: {rfid_code}")
                            return rfid_code  # Return the read RFID code
                    except UnicodeDecodeError:
                        print(f"UnicodeDecodeError: {raw_data}")
                time.sleep(0.1)  # Shorter sleep for responsiveness
        except Exception as e:
            print(f"Error reading from serial port: {e}")
        finally:
            ser.close()  # Close the port

def rfid_monitor_event_driven():
    ser = serial.Serial('COM6', 9600, timeout=1)
    try:
        while True:
            handle_rfid_data(ser)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ser.close()

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_password = request.form['password']
        flash('Password changed successfully!')
        return redirect(url_for('dashboard'))

    return render_template('change_password.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    if request.method == 'POST':
        username = request.form['username']
        rfid_code = read_rfid_from_serial()  # Read RFID code

        if rfid_code:
            try:
                conn = connect_to_db()
                cursor = conn.cursor()
                cursor.execute("INSERT INTO Users (Username, RFIDCode) VALUES (?, ?)", (username, rfid_code))
                conn.commit()
                conn.close()
                flash(f'Użytkownik {username} został dodany pomyślnie!')
            except Exception as e:
                flash(f'Wystąpił błąd: {e}')
                print(f'Error: {e}')
        else:
            flash('Nie udało się odczytać kodu RFID.')

        return redirect(url_for('dashboard'))

    return render_template('add_user.html')

@app.route('/view_logs', methods=['GET', 'POST'])
@login_required
def view_logs():
    conn = connect_to_db()
    cursor = conn.cursor()

    date_filter = datetime.now().date()
    user_filter = None

    if request.method == 'POST':
        selected_date = request.form.get('selected_date')
        selected_user = request.form.get('selected_user')

        if selected_date:
            date_filter = datetime.strptime(selected_date, '%Y-%m-%d').date()
        if selected_user:
            user_filter = int(selected_user)

    query = """
        SELECT u.Username, 
               MAX(CASE WHEN l.BreakNumber % 2 = 1 THEN l.Timestamp END) AS Break1_Start,
               MAX(CASE WHEN l.BreakNumber % 2 = 0 AND l.BreakNumber = 2 THEN l.Timestamp END) AS Break1_End,
               MAX(CASE WHEN l.BreakNumber % 2 = 1 AND l.BreakNumber = 3 THEN l.Timestamp END) AS Break2_Start,
               MAX(CASE WHEN l.BreakNumber % 2 = 0 AND l.BreakNumber = 4 THEN l.Timestamp END) AS Break2_End,
               MAX(CASE WHEN l.BreakNumber % 2 = 1 AND l.BreakNumber = 5 THEN l.Timestamp END) AS Break3_Start,
               MAX(CASE WHEN l.BreakNumber % 2 = 0 AND l.BreakNumber = 6 THEN l.Timestamp END) AS Break3_End
        FROM Logs l
        JOIN Users u ON l.UserID = u.UserID
        WHERE DATE(l.Timestamp) = ?  -- Filter by the selected date
    """

    params = [date_filter]

    if user_filter:
        query += " AND l.UserID = ?"
        params.append(user_filter)

    query += " GROUP BY u.Username ORDER BY u.Username"

    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()

    # Convert timestamps from string to datetime objects
    for i in range(len(logs)):
        logs[i] = list(logs[i])  # Convert Row to list for mutability
        for j in range(1, len(logs[i])):  # Start from index 1, since index 0 is username
            if logs[i][j] is not None:
                logs[i][j] = datetime.fromisoformat(logs[i][j])  # Convert to datetime

    # Print the logs to the console
    for log in logs:
        print(f"Username: {log[0]}")
        print(f"Break 1 Start: {log[1]}")
        print(f"Break 1 End: {log[2]}")
        print(f"Break 2 Start: {log[3]}")
        print(f"Break 2 End: {log[4]}")
        print(f"Break 3 Start: {log[5]}")
        print(f"Break 3 End: {log[6]}")
        print("-" * 20)  # Separator for readability

    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Users")
    users = cursor.fetchall()
    conn.close()

    return render_template('view_logs.html', logs=logs, users=users, date_filter=date_filter)







@app.route('/user_list')
@login_required
def user_list():
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("SELECT UserID, Username FROM Users WHERE RFIDCode IS NOT NULL")
    users = cursor.fetchall()
    conn.close()
    return render_template('user_list.html', users=users)


@app.route('/remove_rfid/<int:user_id>', methods=['POST'])
@login_required
def remove_rfid(user_id):
    try:
        conn = connect_to_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET RFIDCode = NULL WHERE UserID = ?", (user_id,))
        conn.commit()
        conn.close()
        flash('Karta RFID została usunięta dla użytkownika.')
    except Exception as e:
        flash(f'Wystąpił błąd podczas usuwania karty: {e}')

    return redirect(url_for('user_list'))


def log_action(rfid_code, action, break_number):
    user_id = get_user_id_by_rfid(rfid_code)

    if user_id:
        timestamp = datetime.now().isoformat()

        if rfid_code in last_read_time:
            time_since_last_read = (datetime.now() - datetime.fromisoformat(last_read_time[rfid_code])).total_seconds()

            if time_since_last_read < 15:
                print("Odbicie zbyt szybko, spróbuj ponownie później.")
                return

        try:
            conn = connect_to_db()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Logs (UserID, Action, BreakNumber, Timestamp) VALUES (?, ?, ?, ?)",
                           (user_id, action, break_number, timestamp))
            conn.commit()
            conn.close()

            last_read_time[rfid_code] = timestamp  # Update the last read time
            print(f"Akcja zarejestrowana: {action} dla użytkownika ID {user_id}")
        except Exception as e:
            print(f'Wystąpił błąd podczas rejestrowania akcji: {e}')
    else:
        print(f'Nie znaleziono użytkownika z RFID: {rfid_code}')

def get_user_id_by_rfid(rfid_code):
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("SELECT UserID FROM Users WHERE RFIDCode = ?", (rfid_code,))
    user_id = cursor.fetchone()
    conn.close()
    return user_id[0] if user_id else None

if __name__ == '__main__':
    create_db()
    rfid_thread = threading.Thread(target=rfid_monitor_event_driven)
    rfid_thread.start()
    app.run(debug=True)
