import logging

from structlog.testing import capture_logs

from reader._logging import processors
from reader._logging import WrappedLoggerFactory


def test_basic(caplog):
    factory = WrappedLoggerFactory(processors=processors)
    logger = factory.get_logger('lib')

    with caplog.at_level(logging.INFO):
        logger.info('hello world', key='value')

    assert caplog.record_tuples == [('lib', logging.INFO, 'hello world  key=value')]

    caplog.clear()
    factory.enable_native_structlog()

    with caplog.at_level(logging.INFO), capture_logs() as structlog_records:
        logger.info('two')

    assert caplog.record_tuples == []
    assert structlog_records == [{'event': 'two', 'log_level': 'info'}]


def test_exceptions(caplog):
    factory = WrappedLoggerFactory(processors=processors)
    logger = factory.get_logger('lib')

    try:
        1 / 0
    except Exception:
        logger.exception('sad')

    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert record.msg == 'sad  exception="ZeroDivisionError: division by zero"'
    assert record.exc_info
