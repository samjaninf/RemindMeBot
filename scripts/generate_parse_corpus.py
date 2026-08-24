#!/usr/bin/python3
# Generates a seed parse corpus for the Devvit migration's date-parsing
# harness, in the same JSONL schema src/parse_corpus.py logs live traffic in,
# plus a `count` field carrying real-world frequency where known.
#
# Sources: every distinct `recurrence` string in the database (these are raw
# user-typed time strings, with counts), plus a curated list of common forms.
#
# Usage: pipenv run python scripts/generate_parse_corpus.py [database] [output]

import json
import sqlite3
import sys
from datetime import datetime

sys.path.append("src")

import discord_logging

discord_logging.init_logging(debug=True)

import parse_corpus
import utils

parse_corpus.enabled = False

BASE_TIME = utils.datetime_force_utc(datetime.strptime("2026-08-20 12:00:00", "%Y-%m-%d %H:%M:%S"))
TIMEZONES = [None, "America/New_York", "Australia/Sydney"]

CURATED = [
	"1 day", "365 days", "2 weeks", "3 years", "3 months", "24 hours", "5 hrs",
	"20 minutes", "5 seconds", "tomorrow", "Next Thursday at 4pm", "Tonight",
	"2 pm", "eoy", "eom", "eod", "2022-01-01", "10/15/19", "April 9, 2020",
	"January 13th, 2020", "January 5th 2020", "June 2nd", "November 2",
	"August 25, 2018, at 4pm", "September 1, 2019 14:00:00", "august",
	"September", "2027", "2pm", "7:20 pm", "72hr", "1d", "1yr", "7h", "35m",
	"2 weeks with a test string", "3 years with a second date 2014",
	"one day", "one week", "one month", "one year", "a day", "a week",
	"a month", "a year", "next week", "next month", "next year", "next friday",
	"in 3 days", "in an hour", "half a year", "6mo", "90d", "48 hours",
	"tomorrow morning", "tomorrow at 9am", "tonight at 8", "friday", "monday",
	"saturday morning", "christmas", "new years", "election day",
	"1 hour", "2 hours", "12 hours", "30 min", "45 mins", "10m", "15 minutes",
	"2 days", "3 days", "4 days", "5 days", "10 days", "30 days", "60 days",
	"90 days", "100 days", "180 days", "1 week", "2weeks", "1 month",
	"2 months", "6 months", "1 year", "2 years", "5 years", "10 years",
]


def load_recurrence_strings(database_path):
	connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
	try:
		rows = connection.execute(
			"select recurrence, count(*) from reminders "
			"where recurrence is not null group by recurrence order by count(*) desc"
		).fetchall()
	finally:
		connection.close()
	return rows


def main():
	database_path = sys.argv[1] if len(sys.argv) > 1 else "database.db"
	output_path = sys.argv[2] if len(sys.argv) > 2 else "scripts/parse_corpus_seed.jsonl"

	strings = {}
	for time_string in CURATED:
		strings[time_string] = strings.get(time_string, 0)
	for time_string, count in load_recurrence_strings(database_path):
		strings[time_string] = strings.get(time_string, 0) + count

	count_lines = 0
	with open(output_path, "w", encoding="utf-8") as file_handle:
		for time_string, count in strings.items():
			for timezone_string in TIMEZONES:
				result = utils.parse_time(time_string, BASE_TIME, timezone_string)
				file_handle.write(json.dumps({
					"s": time_string,
					"base": parse_corpus._isoformat_utc(BASE_TIME),
					"tz": timezone_string,
					"result": parse_corpus._isoformat_utc(result),
					"stage": None,
					"count": max(count, 1),
				}, ensure_ascii=False) + "\n")
				count_lines += 1

	print(f"{count_lines} lines for {len(strings)} distinct strings written to {output_path}")


if __name__ == "__main__":
	main()
