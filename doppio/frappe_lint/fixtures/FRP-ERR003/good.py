import logging

logger = logging.getLogger(__name__)


def logged():
    try:
        do_something()
    except Exception as e:
        # more than just 'pass' in the body -- must not fire
        logger.error("failed: %s", e)


def bare_except_pass_is_err001s_job_not_err003s():
    # bare 'except: pass' -- FRP-ERR001 already covers the bare-except
    # part; this rule (ERR003) only targets a *narrowed* exception whose
    # body is nothing but 'pass', so it must stay silent here regardless
    # of ERR001's verdict on the same line.
    try:
        do_something()
    except:
        pass
