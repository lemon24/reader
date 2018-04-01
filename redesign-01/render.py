from jinja2 import Template

template = Template(open('template.html').read())
print(template.render())
