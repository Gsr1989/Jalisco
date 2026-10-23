"""web/routes_auth.py — Inicio, login y logout."""
from flask import render_template, request, redirect, url_for, flash, session

from config import supabase
from web.app import app


@app.route('/')
def inicio():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()

        if username == 'Serg890105tm3' and password == 'Serg890105tm3':
            session['admin']    = True
            session['username'] = 'Serg890105tm3'
            return redirect(url_for('admin'))

        resp = supabase.table("verificaciondigitalcdmx")\
            .select("*").eq("username",username).eq("password",password).execute()

        if resp.data:
            u = resp.data[0]
            session['user_id']  = u.get('id')
            session['username'] = u['username']
            session['admin']    = False
            return redirect(url_for('registro_usuario'))

        flash('Usuario o contraseña incorrectos','error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
