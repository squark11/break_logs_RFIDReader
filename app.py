from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from datetime import datetime
import pyodbc
import time
import serial
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Hard-coded admin credentials
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin'

# Placeholder for last read time and breaks
last_read_time = {}

# Database configuration
server = 'KACPER-LAPTOP\\SQLEXPRESS'
database = 'RFIDLog'

def connect_to_db():
    connection_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
    conn = pyodbc.connect(connection_string)
    return conn

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
        try:
            if ser.in_waiting > 0:  # Sprawdzaj tylko, gdy są dane w buforze
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
        except serial.SerialException as e:
            print(f"Error reading from serial port: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")
        time.sleep(0.1)  # Krótsze uśpienie dla płynności

def rfid_monitor_event_driven():
    ser = serial.Serial('COM4', 9600, timeout=1)
    try:
        handle_rfid_data(ser)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ser.close()

def determine_break_number(rfid_code):
    conn = connect_to_db()
    cursor = conn.cursor()

    today = datetime.now().date()

    cursor.execute("""SELECT MAX(BreakNumber) FROM Logs 
                      WHERE UserID = ? AND CAST(Timestamp AS DATE) = ?""",
                   (get_user_id_by_rfid(rfid_code), today))

    max_break_number = cursor.fetchone()[0] or 0
    conn.close()

    return max_break_number + 1

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
        rfid_code = read_rfid_from_serial()  # Odczytaj kod RFID

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
        WHERE CAST(l.Timestamp AS DATE) = ?
    """

    params = [date_filter]

    if user_filter:
        query += " AND l.UserID = ?"
        params.append(user_filter)

    query += " GROUP BY u.Username ORDER BY u.Username"

    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()

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
    cursor.execute("SELECT * FROM Users")
    users = cursor.fetchall()
    conn.close()
    return render_template('user_list.html', users=users)

def log_action(rfid_code, action, break_number):
    user_id = get_user_id_by_rfid(rfid_code)

    if user_id:
        timestamp = datetime.now()

        if rfid_code in last_read_time:
            time_since_last_read = (timestamp - last_read_time[rfid_code]).total_seconds()

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

            last_read_time[rfid_code] = timestamp

            print(f"Dodano wpis: {user_id}, {action}, Break Number: {break_number}, Timestamp: {timestamp}")

        except Exception as e:
            print(f"Błąd przy logowaniu akcji: {e}")

def get_user_id_by_rfid(rfid_code):
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("SELECT UserID FROM Users WHERE RFIDCode = ?", (rfid_code,))
    user_id = cursor.fetchone()
    conn.close()
    return user_id[0] if user_id else None

if __name__ == '__main__':
    threading.Thread(target=rfid_monitor_event_driven, daemon=True).start()
    app.run(debug=True)
