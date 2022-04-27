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


app = Flask(__name__)
bootstrap = Bootstrap(app)

app.config['SECRET_KEY'] = '123456'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///prism.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(50))


class Asset(db.Model):
    __tablename__ = "assets"
    id = db.Column(db.Integer, primary_key=True)
    isin = db.Column(db.String(10))
    asset_name = db.Column(db.String(50))
    price = db.Column(db.Float)
    currency = db.Column(db.String(3))
    yahoo_api = db.Column(db.String(10))


class Holding(db.Model):
    __tablename__ = "holdings"
    id = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Float)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), primary_key=True)


db.create_all()


sqliteConnection = sqlite3.connect('prism.db')
cursor = sqliteConnection.cursor()
sqlite_select_query = """SELECT client_name, SUM(quantity*price)
FROM clients
JOIN holdings on holdings.client_id = clients.id
JOIN assets on assets.id = holdings.asset_id
GROUP BY client_name;"""
cursor.execute(sqlite_select_query)
total_nav = cursor.fetchall()

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
    return render_template("index.html", all_holdings=all_holdings, all_clients=all_clients, all_assets=all_assets, records=total_nav)


@app.route("/value", methods=['GET', 'POST'])
def value():
    all_holdings = db.session.query(Holding).all()
    return render_template("value.html", all_holdings=all_holdings, all_clients=all_clients, all_assets=all_assets, records=total_nav)


@app.route("/share", methods=['GET', 'POST'])
def share():
    all_holdings = db.session.query(Holding).all()
    return render_template("share.html", all_holdings=all_holdings, all_clients=all_clients, all_assets=all_assets, records=total_nav)


@app.route("/order", methods=["GET", "POST"])
def order():
    all_holdings = db.session.query(Holding).all()
    form = EvenForm()
    order_ticket = {}
    if form.validate_on_submit():
        asset = Asset.query.filter_by(asset_name=form.asset.data).first()
        for client in all_clients:
            holding = Holding.query.filter_by(asset_id=asset.id, client_id=client.id).first()
            if form.type.data == "Buy/sell %":
                print(total_nav)
                for nav in total_nav:
                    if nav[0] == client.client_name:
                        order_ticket[client.client_name] = round(float(form.quantity.data)/100 * float(nav[1]) / float(form.price.data))
            elif form.type.data == "Adjust to %":
                for nav in total_nav:
                    if nav[0] == client.client_name:
                        order_ticket[client.client_name] = round(
                            (float(form.quantity.data)/100 - float(holding.quantity) * float(asset.price) / float(nav[1])) * float(nav[1]) / float(asset.price)
                        )
            else:
                nav_all_clients = 0
                for nav in total_nav:
                    nav_all_clients += float(nav[1])
                order_percent = float(form.quantity.data) * float(asset.price) / nav_all_clients
                print(order_percent)
                print(nav_all_clients)
                for nav in total_nav:
                    if nav[0] == client.client_name:
                        order_ticket[client.client_name] = round(order_percent * float(nav[1]) / float(asset.price))
                print("Split evenly nominal")
        order_ticket["asset"] = form.asset.data,
        order_ticket["price"] = form.price.data,
        order_ticket["account"] = form.account.data,
        order_ticket["quantity"] = form.quantity.data,
        order_ticket["type"] = form.type.data
        order_ticket_csv = pd.DataFrame(order_ticket, index=[0])
        order_ticket_csv.to_csv("order.csv")

        return redirect(url_for("execute"))
    return render_template("order.html", form=form)


@app.route("/execute", methods=["GET", "POST"])
def execute():
    all_holdings = db.session.query(Holding).all()
    order_ticket = pd.read_csv('order.csv')
    order_execute = {}
    total_order = 0
    for client in all_clients:
        order_execute[client.client_name] = float(order_ticket[client.client_name].to_string().split('   ')[1])
        total_order += float(order_ticket[client.client_name].to_string().split('   ')[1])
    order_execute["asset"] = order_ticket["asset"].to_string().split('    ')[1]
    order_execute["price"] = float(order_ticket["price"].to_string().split('    ')[1])
    order_execute["account"] = order_ticket["account"].to_string().split('    ')[1]

    asset = Asset.query.filter_by(asset_name=order_execute["asset"]).first()
    asset_holding = {}
    for client in all_clients:
        asset_holding[client.client_name] = Holding.query.filter_by(asset_id=asset.id, client_id=client.id).first().quantity

    if request.method == "POST":
        if request.form.get('Refresh') == 'Refresh':
            total_order = 0
            for client in all_clients:
                order_execute[client.client_name] = float(request.form.get(client.client_name))
                total_order += float(request.form.get(client.client_name))
            order_execute["total_order"] = total_order

            order_ticket["asset"] = order_execute["asset"]
            order_ticket["quantity"] = total_order
            for client in all_clients:
                order_ticket[client.client_name] = order_execute[client.client_name]

            order_ticket_csv = pd.DataFrame(order_ticket, index=[0])
            order_ticket_csv.to_csv("order.csv")
            return render_template("execute.html",
                                   all_holdings=all_holdings,
                                   all_clients=all_clients,
                                   all_assets=all_assets,
                                   order_execute=order_execute,
                                   asset=asset,
                                   asset_holding=asset_holding,
                                   records=total_nav
                               )

        elif request.form.get("Execute") == "Execute":
            for client in all_clients:
                holding_to_update = Holding.query.filter_by(asset_id=asset.id, client_id=client.id).first()
                holding_to_update.quantity += order_execute[client.client_name]
                account_id = Asset.query.filter_by(asset_name=order_execute["account"]).first()
                account_to_update = Holding.query.filter_by(asset_id=account_id.id, client_id=client.id).first()
                account_to_update.quantity -= order_execute[client.client_name] * float(request.form.get("price"))
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
                           asset=asset,
                           asset_holding=asset_holding,
                           records=total_nav
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
        # data = resp.json()
        try:
            asset.price = data["quoteResponse"]["result"][0]["regularMarketPrice"]
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
