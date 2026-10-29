"""Bootstrap .env with only Python's standard library; never print secrets."""
import argparse
import base64
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit


def generate(domain, output):
    domain = domain.strip()
    parsed = urlsplit('https://' + domain)
    if parsed.hostname != domain or any(x in domain for x in '/:@?#\r\n ') or not domain:
        raise ValueError('请输入不含协议、端口或路径的域名。')
    template = Path(__file__).resolve().parents[1] / '.env.example'
    text = template.read_text(encoding='utf-8').replace('workroom.example.com', domain)
    text = text.replace('REPLACE_WITH_RANDOM_SECRET_AT_LEAST_50_CHARACTERS',secrets.token_urlsafe(64))
    text = text.replace('REPLACE_WITH_A_FERNET_KEY',base64.urlsafe_b64encode(os.urandom(32)).decode())
    path = Path(output).resolve()
    with path.open('x',encoding='utf-8') as handle:
        handle.write(text)
    path.chmod(0o600)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('domain')
    parser.add_argument('--output',default='.env')
    args = parser.parse_args()
    try:
        result = generate(args.domain,args.output)
    except (ValueError,FileExistsError) as error:
        parser.error('配置已存在，拒绝覆盖。' if isinstance(error,FileExistsError) else str(error))
    print(f'配置已生成：{result}；密钥只保存在该文件中，请单独备份。')
