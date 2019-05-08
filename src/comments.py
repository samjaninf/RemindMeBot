import logging.handlers
import prawcore

import utils
import static
from classes.reminder import Reminder

log = logging.getLogger("bot")


def database_set_seen(database, comment_seen):
	database.update_keystore("remindme_comment", comment_seen.strftime("%Y-%m-%d %H:%M:%S"))


def database_get_seen(database):
	result = database.get_keystore("remindme_comment")
	if result is None:
		log.warning("Comment time not in database, returning now")
		return utils.datetime_now()
	return utils.parse_datetime_string(result)


def parse_comment(comment, database):
	if comment['author'] == static.ACCOUNT_NAME:
		log.debug("Comment is from remindmebot")
		return None

	if "!remindme" not in comment['body'] and "remindme!" not in comment['body']:
		log.debug("Command not in comment")
		return None

	time = utils.find_reminder_time(comment['body'])

	message_text = utils.find_reminder_message(comment['body'])

	reminder = Reminder(
		source=utils.reddit_link(comment['permalink']),
		message=message_text,
		user=comment['author'],
		requested_date=utils.datetime_from_timestamp(comment['created_utc']),
		time_string=time
	)
	if not reminder.valid:
		return None

	if not database.save_reminder(reminder):
		reminder.result_message = "Something went wrong saving the reminder"
		reminder.valid = False
		log.warning(reminder.result_message)

	return reminder


def process_comment(comment, reddit, database):
	log.info(f"Processing comment {comment['id']} from u/{comment['author']}")
	reminder = parse_comment(comment, database)

	if reminder is None or not reminder.valid:
		log.debug("Not replying")
		return

	commented = False
	if database.get_comment_in_thread(utils.id_from_fullname(comment['link_id'])) is None:
		reddit_comment = reddit.get_comment(comment['id'])
		try:
			reddit.reply_comment(reddit_comment, reminder.render_comment_confirmation())
			commented = True
		except prawcore.exceptions.Forbidden:
			pass



	# check if replied to thread
	# reply to comment or PM
	#
	return


def process_comments(reddit, database):
	comments = reddit.get_keyword_comments("remindme", database_get_seen(database))
	for comment in comments[::-1]:
		process_comment(comment, reddit, database)

	return
