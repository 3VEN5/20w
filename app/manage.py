"""管理命令（在服务器上运行）。

python manage.py new-agency          新建一个机构和它的老板账号（会提示输入）
python manage.py reset-password 登录名   重置某个账号的密码
python manage.py list                列出所有机构和账号
"""
import getpass, sys

import db


def ask(prompt):
    v = input(prompt).strip()
    if not v:
        sys.exit("不能为空")
    return v


def new_password():
    pw = getpass.getpass("密码（至少 8 位）：")
    if len(pw) < 8 or pw != getpass.getpass("再输一次：") :
        sys.exit("密码太短或两次不一致")
    return pw


def main():
    db.init()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    with db.connect() as con:
        if cmd == "new-agency":
            agency, name, login = ask("机构名称："), ask("老板姓名："), ask("老板登录名：")
            pw = new_password()
            aid = con.execute("INSERT INTO agency (name, created) VALUES (?,?)", (agency, db.today())).lastrowid
            con.execute("INSERT INTO user (agency_id, name, login, pw, role) VALUES (?,?,?,?, 'owner')", (aid, name, login, db.hash_pw(pw)))
            print(f"已创建：{agency}，老板账号 {login}。登录后在「设置」里给顾问开账号。")
        elif cmd == "reset-password" and len(sys.argv) > 2:
            pw = new_password()
            n = con.execute("UPDATE user SET pw = ? WHERE login = ?", (db.hash_pw(pw), sys.argv[2])).rowcount
            con.execute("DELETE FROM session WHERE user_id IN (SELECT id FROM user WHERE login = ?)", (sys.argv[2],))
            print("已重置" if n else "找不到这个登录名")
        elif cmd == "list":
            for r in con.execute("SELECT a.name AS agency, u.name, u.login, u.role, u.active FROM user u JOIN agency a ON a.id = u.agency_id ORDER BY a.id, u.id"):
                print(f"{r['agency']}｜{r['name']}｜{r['login']}｜{r['role']}｜{'在用' if r['active'] else '已停用'}")
        else:
            print(__doc__)


if __name__ == "__main__":
    main()
