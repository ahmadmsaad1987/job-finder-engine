# Job finder engine

Daily job search for Ontario legal and contracts roles.
This repository holds only code. Settings and results live in a separate private repository.

## What it does each day
1. Collects jobs from Adzuna, employer careers sites (Workday, Greenhouse, Lever), legal job boards and job-alert emails.
2. Keeps Ontario jobs (and remote roles open to Ontario) with target job titles.
3. Skips jobs already sent on earlier days.
4. Scores each job from 0 to 100: role match (20) + skills overlap (40) + experience level (25) + location (15).
5. Emails the matches with an Excel file, and saves the results.

## Run it on your computer (optional)
```
pip install -r requirements.txt
python run.py --config path/to/config.yaml --data path/to/data --no-email
```

## Tests (no internet needed)
```
pip install pytest
python -m pytest -q
```
