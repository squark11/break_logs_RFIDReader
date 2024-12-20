from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from datetime import datetime, timedelta
from threading import Timer

import sqlite3
import time
import serial
import threading
import pytz


app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'



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


def handle_rfid_data(ser):
    while True:
        with serial_lock:  # Use lock for reading from the port
            if ser.in_waiting > 0:
                raw_data = ser.readline()
                try:
                    rfid_code = raw_data.decode('cp1252', errors='ignore').strip()
                    if rfid_code:
                        close_open_breaks()
                        print(f"RFID Code Read: {rfid_code}")
                        break_number = determine_break_number(rfid_code)
                        action = 'Przerwa ' + str((break_number + 1) // 2) + (' - start' if break_number % 2 == 1 else ' - koniec')

                        # Zarejestruj akcję
                        log_action(rfid_code, action, break_number)
                except UnicodeDecodeError:
                    print(f"UnicodeDecodeError: {raw_data}")
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
        conn.close()
        return 0  # Brak przerwy, jeśli jest poza godzinami przerw

    # Pobranie ostatniego numeru przerwy
    cursor.execute("SELECT MAX(BreakNumber) FROM Logs WHERE UserID = ? AND DATE(Timestamp) = ?",
                   (get_user_id_by_rfid(rfid_code), today))

    max_break_number = cursor.fetchone()[0] or 0
    conn.close()

    # Sprawdzenie, czy wyznaczony numer przerwy jest poprawny
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
                time.sleep(0.1)  # Shorter sleep for responsiveness
        except serial.SerialException:
            flash("Port COM7 nie jest dostępny, kontynuowanie aplikacji bez odczytu RFID.")
            return None  # Return None if there is an issue with COM8
        except Exception as e:
            print(f"Error reading from serial port: {e}")
            return None  # Return None in case of other errors

def rfid_monitor_event_driven():
    ser = serial.Serial('COM8', 9600, timeout=1)
    try:
        while True:
            handle_rfid_data(ser)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ser.close()

def close_open_breaks():
    try:
        conn = connect_to_db()
        cursor = conn.cursor()

        # Pobierz wszystkie otwarte przerwy (BreakNumber nieparzysty, brak odpowiadającej przerwy końcowej)
        cursor.execute("""
            SELECT l1.UserID, l1.BreakNumber, l1.Timestamp
            FROM Logs l1
            LEFT JOIN Logs l2
            ON l1.UserID = l2.UserID AND l1.BreakNumber = l2.BreakNumber - 1
            WHERE l1.BreakNumber % 2 = 1 AND (l2.BreakNumber IS NULL OR l2.BreakNumber = '')
        """)
        open_breaks = cursor.fetchall()

        for user_id, break_number, start_time in open_breaks:
            start_time_dt = datetime.fromisoformat(start_time)
            now = datetime.now()

            time_diff = (now - start_time_dt).total_seconds() / 60  # różnica w minutach

            if time_diff > 30:
                # Zamknij przerwę po 30 minutach
                end_break_number = break_number + 1
                end_time = start_time_dt + timedelta(minutes=30)
                cursor.execute("""
                    INSERT INTO Logs (UserID, Action, BreakNumber, Timestamp) 
                    VALUES (?, ?, ?, ?)
                """, (user_id, f'Przerwa {(break_number + 1) // 2} - koniec', end_break_number, end_time))
                print(f"Automatycznie zamknięto przerwę {break_number // 2} dla użytkownika ID {user_id}.")

        conn.commit()
    except Exception as e:
        print(f'Wystąpił błąd podczas zamykania otwartych przerw: {e}')
    finally:
        conn.close()

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
    close_open_breaks()

    # Otwórz połączenie z bazą
    conn = connect_to_db()
    cursor = conn.cursor()

    date_filter = datetime.now().date()
    user_filter = None

    try:
        if request.method == 'POST':
            selected_date = request.form.get('selected_date')
            selected_user = request.form.get('username')  # Pole z formularza

            if selected_date:
                date_filter = datetime.strptime(selected_date, '%Y-%m-%d').date()
            if selected_user:  # Szukaj UserID na podstawie nazwy użytkownika
                cursor.execute("SELECT UserID FROM Users WHERE Username = ?", (selected_user,))
                user = cursor.fetchone()
                if user:
                    user_filter = user[0]  # Pobierz UserID
                else:
                    flash(f"Użytkownik '{selected_user}' nie został znaleziony.", "warning")

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

        # Konwertuj znaczniki czasu i oblicz czas trwania przerw
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

        cursor.execute("SELECT * FROM Users")
        users = cursor.fetchall()

    finally:
        conn.close()  # Zamknij połączenie na samym końcu

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
        flash(f'Wystąpił błąd podczas usuwania karty: {e}')

    return redirect(url_for('user_list'))


@app.route('/add_break', methods=['GET', 'POST'])
@login_required
def add_break():
    conn = connect_to_db()
    cursor = conn.cursor()

    # Pobierz wszystkich użytkowników do wyboru w formularzu
    cursor.execute("SELECT UserID, Username FROM Users")
    users = cursor.fetchall()

    if request.method == 'POST':
        user_id = request.form['user']
        break_number = int(request.form['break_number'])
        start_time = request.form['start_time']
        end_time = request.form.get('end_time', '').strip()  # Obsługa pustej wartości

        try:
            # Numeracja przerw: Przerwa 1 (1 i 2), Przerwa 2 (3 i 4), Przerwa 3 (5 i 6)
            if break_number == 1:
                break_start = 1
                break_end = 2
            elif break_number == 2:
                break_start = 3
                break_end = 4
            elif break_number == 3:
                break_start = 5
                break_end = 6
            else:
                flash('Niepoprawny numer przerwy.', 'error')
                return redirect(url_for('add_break'))

            timestamp = datetime.now().strftime('%Y-%m-%d')  # Aktualna data

            # Zapisywanie danych do bazy dla rozpoczęcia przerwy
            cursor.execute("""
                INSERT INTO Logs (UserID, BreakNumber, Action, Timestamp)
                VALUES (?, ?, ?, ?)
            """, (user_id, break_start, 'Przerwa ' + str(break_number) + ' - start', f"{timestamp}T{start_time}:00"))

            # Zapisywanie danych do bazy dla zakończenia przerwy tylko jeśli `end_time` jest podane
            if end_time:
                cursor.execute("""
                    INSERT INTO Logs (UserID, BreakNumber, Action, Timestamp)
                    VALUES (?, ?, ?, ?)
                """, (user_id, break_end, 'Przerwa ' + str(break_number) + ' - koniec', f"{timestamp}T{end_time}:00"))

            conn.commit()
            flash('Przerwa została dodana pomyślnie!', 'success')

        except Exception as e:
            flash(f'Wystąpił błąd: {e}', 'error')

        finally:
            conn.close()
            return redirect(url_for('view_logs'))

    return render_template('add_break.html', users=users)


def log_action(rfid_code, action, break_number):
    user_id = get_user_id_by_rfid(rfid_code)

    if user_id:
        timestamp = datetime.now().isoformat()

        if rfid_code in last_read_time:
            time_since_last_read = (datetime.now() - datetime.fromisoformat(last_read_time[rfid_code])).total_seconds()

            if time_since_last_read < 180:
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
