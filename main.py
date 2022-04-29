from flask import Flask, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
import sqlite3
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from werkzeug.utils import redirect
from wtforms import StringField, SubmitField, SelectField
from wtforms.validators import DataRequired
from requests.structures import CaseInsensitiveDict
import requests
import datetime

app = Flask(__name__)
bootstrap = Bootstrap(app)

app.config['SECRET_KEY'] = '123456'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///prism.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_name = db.Column(db.String(50))


class Asset(db.Model):
    __tablename__ = "assets"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    isin = db.Column(db.String(10))
    asset_name = db.Column(db.String(50))
    price = db.Column(db.Float)
    currency = db.Column(db.String(3))
    yahoo_api = db.Column(db.String(10))


class Holding(db.Model):
    __tablename__ = "holdings"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quantity = db.Column(db.Float)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), primary_key=True)


class Ticket(db.Model):
    __tablename__ = "ticket"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), primary_key=True)
    quantity = db.Column(db.Float)
    price = db.Column(db.Float)
    type = db.Column(db.String(50))
    account = db.Column(db.String(3))
    ticket_time = db.Column(db.DateTime)


class Orders(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), primary_key=True)
    quantity = db.Column(db.Float)
    price = db.Column(db.Float)
    account = db.Column(db.String(3))
    type = db.Column(db.String(50))
    ticket_time = db.Column(db.DateTime)


db.create_all()

sqliteConnection = sqlite3.connect('prism.db')
cursor = sqliteConnection.cursor()
sqlite_select_query = """SELECT client_name, SUM(quantity*price)
FROM clients
JOIN holdings on holdings.client_id = clients.id
JOIN assets on assets.id = holdings.asset_id
GROUP BY client_name;"""
cursor.execute(sqlite_select_query)
data = cursor.fetchall()

total_nav = {element[0]: element[1] for element in data}

all_holdings = db.session.query(Holding).all()
all_clients = db.session.query(Client).all()
all_assets = db.session.query(Asset).all()

sql_query = pd.read_sql_query("""SELECT asset_name FROM assets;""", 'sqlite:///prism.db')
df = pd.DataFrame(sql_query)
assets_list = df["asset_name"].to_list()

orders_list = ["Buy/sell %", "Adjust to %", "Split evenly nominal"]
accounts = ["PLN", "EUR", "USD"]


class EvenForm(FlaskForm):
    type = SelectField("Type of operation", choices=orders_list, validators=[DataRequired()])
    asset = SelectField("Asset", choices=assets_list, validators=[DataRequired()])
    quantity = StringField('Quantity', validators=[DataRequired()])
    price = StringField("Price", validators=[DataRequired()])
    account = SelectField("Pay from account", choices=accounts, validators=[DataRequired()])
    submit = SubmitField('Submit')


@app.route("/", methods=['GET', 'POST'])
def home():
    all_holdings = db.session.query(Holding).all()

    return render_template("index.html",
                           all_holdings=all_holdings,
                           all_clients=all_clients,
                           all_assets=all_assets,
                           records=total_nav
                           )


@app.route("/value", methods=['GET', 'POST'])
def value():
    all_holdings = db.session.query(Holding).all()

    return render_template("value.html",
                           all_holdings=all_holdings,
                           all_clients=all_clients,
                           all_assets=all_assets,
                           records=total_nav
                           )


@app.route("/share", methods=['GET', 'POST'])
def share():
    all_holdings = db.session.query(Holding).all()

    return render_template("share.html",
                           all_holdings=all_holdings,
                           all_clients=all_clients,
                           all_assets=all_assets,
                           records=total_nav
                           )


@app.route("/order", methods=["GET", "POST"])
def order():
    form = EvenForm()
    all_tickets = db.session.query(Ticket).all()
    for element in all_tickets:
        db.session.delete(element)
        db.session.commit()

    if form.validate_on_submit():
        asset = Asset.query.filter_by(asset_name=form.asset.data).first()
        for client in all_clients:
            holding = Holding.query.filter_by(asset_id=asset.id, client_id=client.id).first()

            if form.type.data == "Buy/sell %":
                for nav in total_nav.keys():
                    if nav == client.client_name:
                        ticket_time = datetime.datetime.now()
                        ticket = Ticket(client_id=client.id,
                                        asset_id=asset.id,
                                        price=form.price.data,
                                        quantity=round(float(form.quantity.data)/100 * float(total_nav[nav]) / float(form.price.data)),
                                        account=form.account.data,
                                        type=form.type.data,
                                        ticket_time=ticket_time
                                        )
                        db.session.add(ticket)
                        db.session.commit()

            elif form.type.data == "Adjust to %":
                for name in total_nav.keys():
                    if name == client.client_name:
                        ticket_time = datetime.datetime.now()
                        ticket = Ticket(client_id=client.id,
                                        asset_id=asset.id,
                                        price=form.price.data,
                                        quantity=round((float(form.quantity.data)/100 - float(holding.quantity) * float(asset.price) / float(total_nav[name])) * float(total_nav[name]) / float(asset.price)),
                                        account=form.account.data,
                                        type=form.type.data,
                                        ticket_time=ticket_time
                                        )
                        db.session.add(ticket)
                        db.session.commit()

            else:
                nav_all_clients = sum(total_nav.values())
                order_percent = float(form.quantity.data) * float(asset.price) / nav_all_clients
                for name in total_nav.keys():
                    if name == client.client_name:
                        ticket_time = datetime.datetime.now()
                        ticket = Ticket(client_id=client.id,
                                        asset_id=asset.id,
                                        price=form.price.data,
                                        quantity=round(order_percent * float(total_nav[name]) / float(asset.price)),
                                        account=form.account.data,
                                        type=form.type.data,
                                        ticket_time = datetime.datetime.now()
                                        )
                        db.session.add(ticket)
                        db.session.commit()

        return redirect(url_for("execute"))
    return render_template("order.html", form=form)


@app.route("/execute", methods=["GET", "POST"])
def execute():
    all_holdings = db.session.query(Holding).all()
    ticket = db.session.query(Ticket).all()
    total_order = 0
    for execution in ticket:
        total_order += execution.quantity
    first_execution = db.session.query(Ticket).first()
    asset = Asset.query.filter_by(id=first_execution.asset_id).first()
    asset_holding = {}
    for client in all_clients:
        asset_holding[client.client_name] = Holding.query.filter_by(asset_id=asset.id, client_id=client.id).first().quantity

    order_execute = {}
    if request.method == "POST":
        if request.form.get('Refresh') == 'Refresh':
            for client in all_clients:
                ticket_to_update = Ticket.query.filter_by(client_id = client.id).first()
                ticket_to_update.quantity = float(request.form.get(client.client_name))
                ticket_to_update.price = float(request.form.get("price"))
                db.session.commit()

            return render_template("execute.html",
                                   all_holdings=all_holdings,
                                   all_clients=all_clients,
                                   all_assets=all_assets,
                                   order_execute=order_execute,
                                   asset_holding=asset_holding,
                                   records=total_nav,
                                   ticket=ticket,
                                   first_execution=first_execution,
                                   asset=asset,
                                   total_order=total_order
                                   )

        elif request.form.get("Execute") == "Execute":
            for client in all_clients:
                for execution in ticket:
                    if execution.client_id == client.id:
                        order = Orders(
                            asset_id=asset.id,
                            client_id=client.id,
                            quantity=execution.quantity,
                            price=execution.price,
                            account=execution.account,
                            type=execution.type,
                            ticket_time=execution.ticket_time
                        )
                        db.session.add(order)
                        db.session.commit()

                        holding_to_update = Holding.query.filter_by(asset_id=asset.id, client_id=client.id).first()
                        holding_to_update.quantity += execution.quantity
                        account_id = Asset.query.filter_by(asset_name=execution.account).first()
                        account_to_update = Holding.query.filter_by(asset_id=account_id.id, client_id=client.id).first()
                        account_to_update.quantity -= execution.quantity * float(request.form.get("price"))
                        db.session.commit()

            return render_template("index.html",
                                   all_holdings=all_holdings,
                                   all_clients=all_clients,
                                   all_assets=all_assets,
                                   order_execute=order_execute,
                                   asset=asset,
                                   asset_holding=asset_holding,
                                   records=total_nav
                                   )

    return render_template("execute.html",
                           all_holdings=all_holdings,
                           all_clients=all_clients,
                           all_assets=all_assets,
                           order_execute=order_execute,
                           asset_holding=asset_holding,
                           records=total_nav,
                           ticket=ticket,
                           first_execution=first_execution,
                           asset=asset,
                           total_order=total_order
                           )


@app.route("/refresh", methods=["GET", "POST"])
def refresh():
    for asset in all_assets:
        url = f"https://yfapi.net/v6/finance/quote?region=PL&lang=en&symbols={asset.yahoo_api}"
        headers = CaseInsensitiveDict()
        headers["accept"] = "application/json"
        headers["X-API-KEY"] = "S9XL6pukZo6wWwNB3lO4e7DGMZy5I6jjdUcZ3hx9"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        yahoo_data = resp.json()
        try:
            asset.price = yahoo_data["quoteResponse"]["result"][0]["regularMarketPrice"]

        except:
            pass
        db.session.commit()

    return render_template("index.html",
                           all_holdings=all_holdings,
                           all_clients=all_clients,
                           all_assets=all_assets,
                           records=total_nav
                           )


if __name__ == '__main__':
    app.run(debug=True)
