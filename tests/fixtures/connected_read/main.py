"""Read one synthetic message through the declared connection."""
import sys
from capy_script import ConnectionError, Context, ScriptFailure


def main():
    ctx = Context()
    ctx.complete(ctx.connection('lookup').call('read', ctx.request))


if __name__ == '__main__':
    try:
        main()
    except (ConnectionError, ScriptFailure) as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from None
