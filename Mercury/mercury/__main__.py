"""本地 REPL：python -m mercury --user test_user_001，输入 exit 退出。"""

import argparse

from mercury.agent import run_mercury


def main() -> None:
    parser = argparse.ArgumentParser(description="Mercury（墨墨）售后客服 REPL")
    parser.add_argument("--user", default="test_user_001")
    args = parser.parse_args()
    print(f"墨墨已就绪（用户 {args.user}），输入 exit 退出。")
    while True:
        try:
            message = input("你：").strip()
        except EOFError:
            break
        if message == "exit":
            break
        if message:
            print("墨墨：" + run_mercury(args.user, message))


if __name__ == "__main__":
    main()
