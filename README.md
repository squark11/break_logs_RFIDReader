# RFID Employee Break Tracking System
This project is a web-based application that registers and monitors employee break times using RFID technology. It is built with Python and Flask, and connects to a Microsoft SQL Server database for logging and managing break data. The application is designed to streamline employee management by allowing employees to log their break start and end times via RFID card scans.

Features
Employee Management: Add, update, and view employee details, including their RFID codes.
RFID Integration: The system uses an RFID reader connected via COM4 to register employee break times.
Break Logging: Each employee is allowed three breaks per day, with start and end times recorded.
Duplicate Scan Prevention: RFID scans from the same card within 15 seconds are ignored to prevent duplicate entries.
Admin Interface: The admin panel allows authorized users to manage employees and view detailed logs of break times.
Log Filtering: Logs can be filtered by employee name, and break start/end times are displayed in a clean, structured format.
Technology Stack
Frontend: Flask with Jinja2 templates for rendering dynamic web pages.
Backend: Python with Flask, communicating with an RFID reader and SQL Server.
Database: Microsoft SQL Server (using ODBC Driver 17 for SQL Server) to store employee data and break logs.
CSS: Custom styles stored in templates/styles for the frontend design.
