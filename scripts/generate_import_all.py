import inspect
import random


context = {}
exec('from reader import *', context)
context.pop('__builtins__')

print("# importing stuff from reader should type check")
print("# force mypy to check this every time:", random.random())

for name, value in context.items():
    if inspect.ismodule(value):
        continue
    print('from reader import', name)
