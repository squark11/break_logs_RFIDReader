from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from datetime import datetime
import sqlite3
import time
import serial
import threading
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'

logging.basicConfig(
    filename="logs.txt",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Login manager setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Hard-coded admin credentials
ADMIN_USERNAME = 'root'
ADMIN_PASSWORD = 'pass2'

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

last_read_time = {}  # Słownik w formacie: {rfid_code: last_read_timestamp}

def handle_rfid_data(ser):
    while True:
        with serial_lock:  # Użyj blokady podczas czytania z portu
            if ser.in_waiting > 0:
                raw_data = ser.readline()
                try:
                    rfid_code = raw_data.decode('cp1252', errors='ignore').strip()
                    if rfid_code:
                        print(f"RFID Code Read: {rfid_code}")

                        current_time = time.time()
                        if rfid_code in last_read_time:
                            time_since_last_read = current_time - last_read_time[rfid_code]
                            if time_since_last_read < 180:
                                print(f"Zignorowano powtórne odczytanie karty: {rfid_code} (czas od ostatniego odczytu: {time_since_last_read:.2f}s)")
                                continue

                        # Zaktualizuj czas ostatniego odczytu dla tego kodu RFID
                        last_read_time[rfid_code] = current_time

                        break_number = determine_break_number(rfid_code)
                        action = 'Przerwa ' + str((break_number + 1) // 2) + (' - start' if break_number % 2 == 1 else ' - koniec')
                        log_action(rfid_code, action, break_number)
                except UnicodeDecodeError:
                    print(f"UnicodeDecodeError: {raw_data}")
                    logging.error(error_message)
        time.sleep(0.1)


def determine_break_number(rfid_code):
    conn = connect_to_db()
    cursor = conn.cursor()

    today = datetime.now().date()
    current_time = datetime.now().time()

    # Określenie, która przerwa ma być zarejestrowana w zależności od godziny
    if current_time >= datetime.strptime("09:00", "%H:%M").time() and current_time < datetime.strptime("12:00",
                                                                                                       "%H:%M").time():
        break_number = 1
    elif current_time >= datetime.strptime("12:00", "%H:%M").time() and current_time < datetime.strptime("16:00",
                                                                                                         "%H:%M").time():
        break_number = 3
    elif current_time >= datetime.strptime("16:00", "%H:%M").time() and current_time < datetime.strptime("19:00",
                                                                                                         "%H:%M").time():
        break_number = 5
    else:
        break_number = 0  # Brak przerwy, jeśli jest poza godzinami przerw

    # Pobranie ostatniego numeru przerwy
    cursor.execute("SELECT MAX(BreakNumber) FROM Logs WHERE UserID = ? AND DATE(Timestamp) = ?",
                   (get_user_id_by_rfid(rfid_code), today))

    max_break_number = cursor.fetchone()[0] or 0
    conn.close()

    return break_number if break_number > max_break_number else max_break_number + 1

def read_rfid_from_serial():
    with serial_lock:  # Use lock to prevent access conflicts
        try:
            ser = serial.Serial('COM7', 9600, timeout=1)
            while True:
                if ser.in_waiting > 0:  # Check if data is available in the buffer
                    raw_data = ser.readline()
                    try:
                        rfid_code = raw_data.decode('cp1252', errors='ignore').strip()
                        if rfid_code:
                            print(f"RFID Code Read: {rfid_code}")
                            return rfid_code  # Return the read RFID code
                    except UnicodeDecodeError:
                        print(f"UnicodeDecodeError: {raw_data}")
                        logging.error(error_message)
                time.sleep(0.1)  # Shorter sleep for responsiveness
        except serial.SerialException:
            flash("Port COM7 nie jest dostępny, kontynuowanie aplikacji bez odczytu RFID.")
            logging.error(error_message)
            return None  # Return None if there is an issue with COM8
        except Exception as e:
            print(f"Error reading from serial port: {e}")
            logging.error(error_message)
            return None  # Return None in case of other errors

def rfid_monitor_event_driven():
    ser = serial.Serial('COM8', 9600, timeout=1)
    try:
        while True:
            handle_rfid_data(ser)
    except Exception as e:
        logging.error(error_message)
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
            # Check if the RFID code already exists in the database
            conn = connect_to_db()
            cursor = conn.cursor()
            cursor.execute("SELECT UserID FROM Users WHERE RFIDCode = ?", (rfid_code,))
            existing_user = cursor.fetchone()

            if existing_user:
                flash('Ta karta RFID jest już przypisana do innego użytkownika.', 'error')
            else:
                try:
                    cursor.execute("INSERT INTO Users (Username, RFIDCode) VALUES (?, ?)", (username, rfid_code))
                    conn.commit()
                    flash(f'Użytkownik {username} został dodany pomyślnie!', 'success')
                except Exception as e:
                    logging.error(error_message)
                    flash(f'Wystąpił błąd: {e}', 'error')
                    print(f'Error: {e}')
            conn.close()
        else:
            flash('Nie udało się odczytać kodu RFID.', 'error')

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
               MAX(CASE WHEN l.BreakNumber = 1 THEN l.Timestamp END) AS Break1_Start,
               MAX(CASE WHEN l.BreakNumber = 2 THEN l.Timestamp END) AS Break1_End,
               MAX(CASE WHEN l.BreakNumber = 3 THEN l.Timestamp END) AS Break2_Start,
               MAX(CASE WHEN l.BreakNumber = 4 THEN l.Timestamp END) AS Break2_End,
               MAX(CASE WHEN l.BreakNumber = 5 THEN l.Timestamp END) AS Break3_Start,
               MAX(CASE WHEN l.BreakNumber = 6 THEN l.Timestamp END) AS Break3_End
        FROM Logs l
        JOIN Users u ON l.UserID = u.UserID
        WHERE DATE(l.Timestamp) = ?
    """

    params = [date_filter]

    if user_filter:
        query += " AND l.UserID = ?"
        params.append(user_filter)

    query += " GROUP BY u.Username ORDER BY COALESCE(Break1_Start, Break2_Start, Break3_Start) ASC"

    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()

    # Convert timestamps and calculate break durations in hh:mm:ss format
    for i in range(len(logs)):
        logs[i] = list(logs[i])
        for j in range(1, 7):  # Timestamps: indexes 1-6
            if logs[i][j] is not None:
                logs[i][j] = datetime.fromisoformat(logs[i][j])

        # Calculate durations in hh:mm:ss format
        for j in range(1, 4):  # For Break1, Break2, and Break3
            start_idx = 2 * j - 1  # Start timestamp index
            end_idx = 2 * j  # End timestamp index

            if logs[i][start_idx] and logs[i][end_idx]:
                duration_seconds = (logs[i][end_idx] - logs[i][start_idx]).total_seconds()
                hours = int(duration_seconds // 3600)
                minutes = int((duration_seconds % 3600) // 60)
                seconds = int(duration_seconds % 60)
                logs[i].append(f"{hours:02}:{minutes:02}:{seconds:02}")
            else:
                logs[i].append('Brak')

    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Users")
    users = cursor.fetchall()
    conn.close()

    return render_template('view_logs.html', logs=logs, users=users, date_filter=date_filter)

@app.route('/delete_log', methods=['POST'])
@login_required
def delete_log():
    data = request.get_json()
    username = data.get('username')
    break_number = data.get('break_number')

    if not username or not break_number:
        return jsonify({'error': 'Brak wymaganych danych (Username lub BreakNumber).'}), 400

    conn = connect_to_db()
    cursor = conn.cursor()

    # Znajdź UserID na podstawie Username
    cursor.execute("SELECT UserID FROM Users WHERE Username = ?", (username,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({'error': 'Nie znaleziono użytkownika.'}), 404

    user_id = user[0]

    # Usuń log na podstawie UserID i BreakNumber
    cursor.execute("DELETE FROM Logs WHERE UserID = ? AND BreakNumber = ?", (user_id, break_number))
    if cursor.rowcount == 0:
        conn.close()
        return jsonify({'error': 'Nie znaleziono logu do usunięcia.'}), 404

    conn.commit()
    conn.close()

    return jsonify({'message': 'Log został usunięty.'}), 200



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
        logging.error(error_message)
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
