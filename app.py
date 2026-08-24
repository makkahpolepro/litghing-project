import os
import qrcode
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import sqlite3

app = Flask(__name__)
app.secret_key = 'makkah_lighting_secret_key_2026'

DB_NAME = 'lighting_database.db'
UPLOAD_FOLDER = 'uploads'
QR_FOLDER = 'static/qrs'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS poles (
            pole_ID TEXT PRIMARY KEY,
            Pole_Height TEXT,
            Fixture_Type TEXT,
            Lamp_Type TEXT,
            Pole_Status TEXT,
            lat TEXT,
            lng TEXT,
            technician_notes TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    cursor.execute('SELECT COUNT(*) FROM admin_config')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO admin_config (username, password) VALUES (?, ?)', ('admin', 'admin123'))

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS technicians (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def generate_qr_code(pole_id):
    """توليد كود QR فريد لكل عمود يرتبط برابط صفحة العمود"""
    safe_id = str(pole_id).strip().replace('/', '_').replace('\\', '_')
    url = f"http://192.168.0.118:5000/pole/{safe_id}" # استبدل الرابط بـ IP الخادم المحلي عند النشر الميداني
    img = qrcode.make(url)
    qr_path = os.path.join(QR_FOLDER, f"{safe_id}.png")
    img.save(qr_path)

@app.route('/')
def index():
    if 'admin_logged' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM admin_config WHERE username = ? AND password = ?', (u, p))
        admin = cursor.fetchone()
        conn.close()
        if admin:
            session['admin_logged'] = True
            return redirect(url_for('dashboard'))
        flash('بيانات الدخول غير صحيحة', 'danger')
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'admin_logged' not in session:
        return redirect(url_for('admin_login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_admin':
            new_user = request.form.get('admin_username')
            new_pass = request.form.get('admin_password')
            if new_user and new_pass:
                cursor.execute('UPDATE admin_config SET username = ?, password = ? WHERE id = 1', (new_user, new_pass))
                conn.commit()
                flash('تم تحديث بيانات دخول الإدارة بنجاح', 'success')

        elif action == 'add_tech':
            t_user = request.form.get('tech_username')
            t_pass = request.form.get('tech_password')
            t_name = request.form.get('tech_name')
            try:
                cursor.execute('INSERT INTO technicians (username, password, full_name) VALUES (?, ?, ?)', (t_user, t_pass, t_name))
                conn.commit()
                flash('تم إضافة حساب الفني بنجاح', 'success')
            except:
                flash('اسم المستخدم للفني موجود مسبقاً', 'danger')

        elif action == 'delete_tech':
            t_id = request.form.get('tech_id')
            cursor.execute('DELETE FROM technicians WHERE id = ?', (t_id,))
            conn.commit()
            flash('تم حذف حساب الفني بنجاح', 'info')

        elif action == 'upload_excel':
            file = request.files.get('excel_file')
            if file and file.filename.endswith(('.xlsx', '.xls')):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                try:
                    df = pd.read_excel(file_path)
                    df.columns = df.columns.str.strip()
                    
                    data_to_insert = []
                    pole_ids_list = []
                    
                    for _, row in df.iterrows():
                        p_id_val = None
                        for col in df.columns:
                            if 'pole' in col.lower() and 'id' in col.lower():
                                p_id_val = row[col]
                                break
                        if not p_id_val or pd.isna(p_id_val):
                            p_id_val = row.iloc[0]
                        
                        p_id = str(p_id_val).strip()
                        
                        def get_val(keywords):
                            for col in df.columns:
                                if any(kw in col.lower() for kw in keywords):
                                    val = row[col]
                                    return str(val).strip() if not pd.isna(val) else ''
                            return ''

                        height = get_val(['height'])
                        f_type = get_val(['fixture'])
                        l_type = get_val(['lamp'])
                        status = get_val(['status']) or 'سليم'
                        lat = get_val(['lat', 'latitude', 'y'])
                        lng = get_val(['lng', 'long', 'longitude', 'x'])

                        data_to_insert.append((p_id, height, f_type, l_type, status, lat, lng))
                        pole_ids_list.append(p_id)
                    
                    cursor.executemany('''
                        INSERT INTO poles (pole_ID, Pole_Height, Fixture_Type, Lamp_Type, Pole_Status, lat, lng)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(pole_ID) DO UPDATE SET
                        Pole_Height=excluded.Pole_Height,
                        Fixture_Type=excluded.Fixture_Type,
                        Lamp_Type=excluded.Lamp_Type,
                        Pole_Status=excluded.Pole_Status,
                        lat=excluded.lat,
                        lng=excluded.lng
                    ''', data_to_insert)
                    conn.commit()

                    # توليد صور QR للأعمدة المرفوعة (توليدها في الخلفية)
                    for pid in pole_ids_list:
                        generate_qr_code(pid)
                    
                    flash(f'تم رفع وتحديث {len(data_to_insert)} عمود وتوليد أكواد الـ QR بنجاح!', 'success')
                except Exception as e:
                    flash(f'خطأ في قراءة ملف الاكسل: {e}', 'danger')

        elif action == 'add_pole':
            p_id = request.form.get('pole_ID')
            height = request.form.get('Pole_Height')
            f_type = request.form.get('Fixture_Type')
            l_type = request.form.get('Lamp_Type')
            status = request.form.get('Pole_Status')
            lat = request.form.get('lat')
            lng = request.form.get('lng')
            try:
                cursor.execute('''
                    INSERT INTO poles (pole_ID, Pole_Height, Fixture_Type, Lamp_Type, Pole_Status, lat, lng)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (p_id, height, f_type, l_type, status, lat, lng))
                conn.commit()
                generate_qr_code(p_id)
                flash('تم إضافة العمود وتوليد الـ QR بنجاح', 'success')
            except:
                flash('معرف العمود موجود مسبقاً', 'danger')

        elif action == 'delete_pole':
            p_id = request.form.get('pole_ID')
            cursor.execute('DELETE FROM poles WHERE pole_ID = ?', (p_id,))
            conn.commit()
            flash('تم حذف العمود بنجاح', 'info')

    cursor.execute('SELECT * FROM admin_config WHERE id = 1')
    admin_info = cursor.fetchone()
    cursor.execute('SELECT * FROM technicians')
    technicians = cursor.fetchall()

    search = request.args.get('search', '')
    if search:
        cursor.execute("SELECT * FROM poles WHERE pole_ID LIKE ? OR Lamp_Type LIKE ?", ('%' + search + '%', '%' + search + '%'))
    else:
        cursor.execute('SELECT * FROM poles')
    
    poles = cursor.fetchall()
    conn.close()
    
    return render_template('dashboard.html', poles=poles, search=search, admin_info=admin_info, technicians=technicians)

@app.route('/pole/<pole_id>')
def pole_detail(pole_id):
    """صفحة العمود التي تظهر للمستخدم عند مسح كود الـ QR"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM poles WHERE pole_ID = ?', (pole_id,))
    pole = cursor.fetchone()
    conn.close()
    
    if not pole:
        return "العمود غير موجود", 404
    return render_template('pole_detail.html', pole=pole)

@app.route('/technician/login', methods=['GET', 'POST'])
def technician_login():
    pole_id = request.args.get('pole_id', '')
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        target_pole = request.form.get('pole_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM technicians WHERE username = ? AND password = ?', (u, p))
        tech = cursor.fetchone()
        conn.close()
        
        if tech:
            session['tech_logged'] = True
            session['tech_id'] = tech['id']
            session['tech_username'] = tech['username']
            return redirect(url_for('technician_edit', pole_id=target_pole))
        flash('بيانات دخول الفني خاطئة', 'danger')
    return render_template('technician_login.html', pole_id=pole_id)

@app.route('/technician/edit/<pole_id>', methods=['GET', 'POST'])
def technician_edit(pole_id):
    if 'tech_logged' not in session:
        return redirect(url_for('technician_login', pole_id=pole_id))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # صلاحية الفني لتعديل بيانات حسابه الشخصي (اسم المستخدم وكلمة المرور)
        if action == 'update_my_account':
            new_u = request.form.get('new_username')
            new_p = request.form.get('new_password')
            t_id = session.get('tech_id')
            try:
                cursor.execute('UPDATE technicians SET username = ?, password = ? WHERE id = ?', (new_u, new_p, t_id))
                conn.commit()
                session['tech_username'] = new_u
                flash('تم تحديث بيانات حسابك الشخصي بنجاح', 'success')
            except:
                flash('اسم المستخدم الجديد مستخدم مسبقاً', 'danger')
                
        # صلاحية الفني لتعديل بيانات العمود
        elif action == 'update_pole_data':
            status = request.form.get('Pole_Status')
            height = request.form.get('Pole_Height')
            f_type = request.form.get('Fixture_Type')
            l_type = request.form.get('Lamp_Type')
            notes = request.form.get('technician_notes')
            
            cursor.execute('''
                UPDATE poles SET Pole_Height = ?, Fixture_Type = ?, Lamp_Type = ?, Pole_Status = ?, technician_notes = ?, last_updated = CURRENT_TIMESTAMP
                WHERE pole_ID = ?
            ''', (height, f_type, l_type, status, notes, pole_id))
            conn.commit()
            flash('تم حفظ تحديثات بيانات العمود بنجاح', 'success')

    cursor.execute('SELECT * FROM poles WHERE pole_ID = ?', (pole_id,))
    pole = cursor.fetchone()
    
    cursor.execute('SELECT * FROM technicians WHERE id = ?', (session.get('tech_id'),))
    my_account = cursor.fetchone()
    
    conn.close()
    
    if not pole:
        return "العمود غير موجود", 404
        
    return render_template('technician_edit.html', pole=pole, my_account=my_account)

@app.route('/technician/logout')
def technician_logout():
    pole_id = request.args.get('pole_id', '')
    session.pop('tech_logged', None)
    session.pop('tech_id', None)
    session.pop('tech_username', None)
    return redirect(url_for('technician_login', pole_id=pole_id))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)