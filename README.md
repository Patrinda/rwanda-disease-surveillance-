# Rwanda Disease Surveillance and Outbreak Monitoring System

A Django project for the course Web Technologies and API Services (AUCA).
Health staff record patients and case reports, the system compares each week
with the usual level and raises Watch and Alert signals, and a dashboard and
a district map show where cases are concentrated. The final project adds a
token protected API, a weather feed, a forecasting model and a forecast
dashboard that updates as new reports arrive.

All people, phone numbers and case counts in the demonstration data are fictional.

## Apps

| App | Purpose |
|---|---|
| `accounts` | Roles (Facility Reporter, District Officer, National Administrator), user profile, login and logout |
| `locations` | Provinces and districts of Rwanda (30 districts are loaded by a migration), district profile pages |
| `surveillance` | Diseases, patients, case reports, outbreaks, alert rule, dashboard, map |
| `forecasting` | REST style API with tokens, Open-Meteo weather, the next week forecast model, stored predictions, forecast page, API guide |

## Quick start (Windows PowerShell)

```
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo --reset
python manage.py fetch_weather
python manage.py train_model
python manage.py runserver
```

`fetch_weather` needs internet (it reads Open-Meteo). Without internet use
`python manage.py fetch_weather --synthetic`, which stores clearly marked
artificial weather. A trained model is already included, so `train_model` is
only needed after new data or a new scikit-learn version.

Open http://127.0.0.1:8000/ in the browser.

On Mac or Linux use `python3` and `source venv/bin/activate`.

## Demo accounts

| Username | Password | Role |
|---|---|---|
| admin | Admin@2026 | National Administrator and Django superuser |
| officer_kayonza | Officer@2026 | District Officer, Kayonza |
| officer_huye | Officer@2026 | District Officer, Huye |
| reporter_kigali | Reporter@2026 | Facility Reporter, Gasabo |

## What each role can do

| Action | Reporter | Officer | Administrator |
|---|---|---|---|
| View dashboard, map, alerts | yes | yes | yes |
| Add patients and case reports (own district) | yes | yes | yes |
| Edit a report | own reports | reports in own district | all |
| Declare and close outbreaks, export CSV | no | yes | yes |
| Add, edit, delete diseases; delete patients and reports | no | no | yes |

## Alert rule

For every disease in every district: current = cases reported in the latest 7 days,
baseline = average weekly cases in the 28 days before that.
Alert when current is at least the disease multiplier times the baseline and at
least the minimum number of cases. Watch when current is at least 1.5 times the baseline.
The multiplier and minimum are set per disease on the Diseases page.

## Final project: API, model and forecast

1. Data in: the API (`/api/v1/`) accepts case reports with `POST /api/v1/reports/` using
   `Authorization: Token <key>`. Keys are created on the API guide page or with
   `python manage.py create_api_token <username>`. Weather comes from Open-Meteo.
2. Model: `train_model` fits a scikit-learn gradient boosting model (Poisson loss) on the
   reports plus two years of synthetic outbreak history, checks it on the latest unseen
   weeks, and stores the scores in the `ModelRun` table. `python manage.py train_model --from-api URL --token KEY`
   trains from the API instead of the database.
3. Deployment: the saved model is loaded by Django. Every new report refreshes the
   forecast for its district and disease, and `python manage.py refresh_predictions` refreshes everything.
4. Dashboard: expected cases next week, alert chance per district and disease, weather,
   and the model scores. Officers and reporters only see their own district.

Demo of live data: `python manage.py simulate_incoming --outbreak "Cholera:Huye"` sends
new reports through the same rules and the forecast on the dashboard changes.

Honest limits: the data are fictional, the model is better than the "same as this week"
rule on unseen weeks but not on the national weekly total during a sudden surge, and weather
is not used by default because it did not improve the scores.

## Useful commands

```
python manage.py test                     run the 112 automated tests
python manage.py seed_demo --reset        rebuild fresh demonstration data (dates are relative to today)
python manage.py createsuperuser          make another administrator
python manage.py check                    check the project for problems
```

## Database

SQLite is the default and needs no setup. To use MySQL set these environment
variables before running: `DB_ENGINE=mysql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
`DB_HOST`, `DB_PORT`, and install `mysqlclient`.

## Folder map

```
rwanda_surveillance/  settings.py and project level urls.py (the inner package)
accounts/      roles, profile, login
locations/     provinces and districts
surveillance/  main models, forms, views, alert rule, seed command, tests
forecasting/   API, weather, model, predictions, commands, tests, saved model file
templates/     base.html (AdminLTE layout) and every page
static/        AdminLTE, Bootstrap, Chart.js, Leaflet (all stored locally), our css and js, the map file
tools/         script used to build the map file from the shapefile
docs/          ER diagram and screenshots
```
