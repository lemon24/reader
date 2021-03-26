import pytest

from reader._config import Config


CONFIG_INIT_DATA = [
    (Config({}), {'default': {}}),
    (Config({}, sections={'cli', 'app'}), {'default': {}, 'cli': {}, 'app': {}}),
    (
        Config({'reader': {'k': 'v'}}, sections={'cli', 'app'}),
        {'default': {'reader': {'k': 'v'}}, 'cli': {}, 'app': {}},
    ),
    (
        Config({'default': {'reader': {'k': 'v'}}}, sections={'cli', 'app'}),
        {'default': {'reader': {'k': 'v'}}, 'cli': {}, 'app': {}},
    ),
]


@pytest.mark.parametrize('config, data', CONFIG_INIT_DATA)
def test_config_init(config, data):
    assert config.data == data


def test_config_init_error():
    with pytest.raises(ValueError):
        Config({'default': {'reader': {}}, 'reader': {}})


def test_config_merged():
    config = Config(
        {
            'url': 'default-url',
            'plugins': {'default-plugin': None, 'another-plugin': 1},
            'cli': {'url': 'cli-url'},
            'app': {'plugins': {'app-plugin': None, 'another-plugin': 2}},
        },
        sections={'cli', 'app'},
        merge_keys={
            'plugins',
        },
    )

    assert config.merged('cli') == {
        'url': 'cli-url',
        'plugins': {'default-plugin': None, 'another-plugin': 1},
    }

    assert config.merged('app') == {
        'url': 'default-url',
        'plugins': {'default-plugin': None, 'another-plugin': 2, 'app-plugin': None},
    }


def test_config_merged_recursive():
    config = Config(
        {
            'reader': {'plugins': {'default-reader-plugin': None}},
            'plugins': {'default-plugin': None},
            'app': {
                'reader': {'plugins': {'app-reader-plugin': None}},
                'plugins': {'app-plugin': None},
            },
        },
        sections={
            'app',
        },
        merge_keys={'reader', 'plugins'},
    )
    assert config.merged('app') == {
        'reader': {
            'plugins': {'default-reader-plugin': None, 'app-reader-plugin': None}
        },
        'plugins': {'default-plugin': None, 'app-plugin': None},
    }


def test_config_all():
    config = Config(
        {
            'url': 'default-url',
            'nested': {'default-key': 'default-nested'},
            'cli': {
                'url': 'cli-url',
                'nested': {'cli-key': 'cli-nested'},
            },
        },
        sections={'cli', 'app'},
        merge_keys={
            'nested',
        },
    )

    config.all['url'] = 'new-url'
    assert config.data == {
        'default': {
            'url': 'new-url',
            'nested': {'default-key': 'default-nested'},
        },
        'cli': {
            'url': 'new-url',
            'nested': {'cli-key': 'cli-nested'},
        },
        'app': {
            'url': 'new-url',
        },
    }

    config.all['nested'] = {'new-key': 'new-value'}
    assert config.data == dict.fromkeys(
        ('default', 'cli', 'app'),
        {
            'url': 'new-url',
            'nested': {'new-key': 'new-value'},
        },
    )
