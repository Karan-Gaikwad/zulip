import sys
import logging
import traceback
import platform

from django.core import mail
from django.utils.log import AdminEmailHandler
from django.views.debug import ExceptionReporter, get_exception_reporter_filter

def format_record(record):
    """
    Given a Django error LogRecord, format and return the interesting details,
    for use by notification mechanisms like Humbug and e-mail.
    """
    subject = '%s: %s' % (platform.node(), record.getMessage())

    if record.exc_info:
        stack_trace = ''.join(traceback.format_exception(*record.exc_info))
    else:
        stack_trace = 'No stack trace available'

    try:
        user = record.request.user
        user_info = "%s (%s)" % (user.userprofile.full_name, user.email)
    except Exception:
        # Error was triggered by an anonymous user.
        user_info = "Anonymous user (not logged in)"

    return (subject, stack_trace, user_info)

class AdminHumbugHandler(logging.Handler):
    """An exception log handler that Humbugs log entries to the Humbug realm.

    If the request is passed as the first argument to the log record,
    request data will be provided in the email report.
    """

    # adapted in part from django/utils/log.py

    def __init__(self):
        logging.Handler.__init__(self)

    def emit(self, record):
        # We have to defer imports to avoid circular imports in settings.py.
        from zephyr.models import Recipient
        from zephyr.lib.actions import internal_send_message


        try:
            request = record.request

            filter = get_exception_reporter_filter(request)
            request_repr = "Request info:\n~~~~\n"
            request_repr += "- path: %s\n" % (request.path,)
            if request.method == "GET":
                request_repr += "- GET: %s\n" % (request.GET,)
            elif request.method == "POST":
                request_repr += "- POST: %s\n" % (filter.get_post_parameters(request),)
            for field in ["REMOTE_ADDR", "QUERY_STRING", "SERVER_NAME"]:
                request_repr += "- %s: \"%s\"\n" % (field, request.META.get(field, "(None)"))
            request_repr += "~~~~"
        except Exception:
            request_repr = "Log record message:\n%s" % (record.getMessage(),)

        subject, stack_trace, user_info = format_record(record)

        try:
            internal_send_message("humbug+errors@humbughq.com",
                    Recipient.STREAM, "devel", self.format_subject(subject),
                    "Error generated by %s\n\n~~~~ pytb\n%s\n\n~~~~\n%s" % (
                    user_info, stack_trace, request_repr))
        except:
            # If this breaks, complain loudly but don't pass the traceback up the stream
            # However, we *don't* want to use logging.exception since that could trigger a loop.
            logging.warning("Reporting an exception triggered an exception!", exc_info=True)

    def format_subject(self, subject):
        """
        Escape CR and LF characters, and limit length to MAX_SUBJECT_LENGTH.
        """
        from zephyr.models import MAX_SUBJECT_LENGTH
        formatted_subject = subject.replace('\n', '\\n').replace('\r', '\\r')
        return formatted_subject[:MAX_SUBJECT_LENGTH]

class HumbugAdminEmailHandler(AdminEmailHandler):
    """An exception log handler that emails log entries to site admins.

    If the request is passed as the first argument to the log record,
    request data will be provided in the email report.
    """
    def emit(self, record):
        try:
            request = record.request
            filter = get_exception_reporter_filter(request)
            request_repr = filter.get_request_repr(request)
        except Exception:
            request = None
            request_repr = "Log record message:\n%s" % (record.getMessage(),)

        subject, stack_trace, user_info = format_record(record)
        message = "Error generated by %s\n\n%s\n\n%s" % (user_info, stack_trace,
                                                         request_repr)

        try:
            reporter = ExceptionReporter(request, is_email=True, *record.exc_info)
            html_message = self.include_html and reporter.get_traceback_html() or None
        except Exception:
            html_message = None
        mail.mail_admins(self.format_subject(subject), message, fail_silently=True,
                         html_message=html_message)
