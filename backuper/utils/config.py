import yaml
from .params import args
import jinja2
import re


def load_yaml(f):

    return yaml.load(f)


def parse_vars():

    if args.vars_file is not None:
        _vars = load_yaml(args.vars_file)
    else:
        _vars = {}

    return _vars


def parse_extra_vars():

    if args.extra_vars is not None:
        extra_vars = dict(re.findall(r'(\S+)=(".*?"|\S+)', args.extra_vars))
    else:
        extra_vars = {}

    return extra_vars


def get_jinja_template(r_template, args):

    t = jinja2.Template(r_template, undefined=jinja2.StrictUndefined)

    return t.render(args)


def merge_vars():

    _vars = parse_vars()
    extra_vars = parse_extra_vars()
    _vars.update(extra_vars)

    return _vars


def parse_action():

    _vars = merge_vars()
    action = load_yaml(get_jinja_template(args.action_file.read(), _vars))

    return action


action = parse_action()
