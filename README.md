# Rwanda Disease Surveillance and Outbreak Monitoring System

A Django project for the course Web Technologies and API Services (AUCA).
Health staff record patients and case reports, the system compares each week
with the usual level and raises Watch and Alert signals, and a dashboard and
a district map show where cases are concentrated.

All people, phone numbers and case counts in the demonstration data are fictional.

## Apps

| App | Purpose |
|---|---|
| `accounts` | Roles (Facility Reporter, District Officer, National Administrator), user profile, login and logout |
| `locations` | Provinces and districts of Rwanda (30 districts are loaded by a migration), district profile pages |
| `surveillance` | Diseases, patients, case reports, outbreaks, alert rule, dashboard, map |

## Quick start (Windows PowerShell)

```
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo --reset
python manage.py runserver
```

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

## Useful commands

```
python manage.py test                     run the 57 automated tests
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
templates/     base.html (AdminLTE layout) and every page
static/        AdminLTE, Bootstrap, Chart.js, Leaflet (all stored locally), our css and js, the map file
tools/         script used to build the map file from the shapefile
docs/          ER diagram and screenshots
```
