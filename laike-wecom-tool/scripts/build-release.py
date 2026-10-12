"""仅打包明列源码、说明和合成数据验证结果；不收集本机配置或数据库。"""
import hashlib
import json
import zipfile
from pathlib import Path


ROOT=Path(__file__).resolve().parent.parent
FILES=['README.md','run.py','sender.py','manage.py','requirements.txt','requirements.lock',
       'requirements-dev.txt','requirements-sender.txt','requirements-sender.lock','package.json','Dockerfile','compose.yaml',
       '.gitignore','.dockerignore','start-demo.bat','start-server.bat','start-sender.bat']
DIRECTORIES=['toolbox','sender','deploy','docs','tests','scripts']
EVIDENCE=['dashboard.png','templates.png','manual-review.png','mobile.png','benchmark.json',
          'browser-check.json','windows-sender-check.json','release-smoke.json','tests.xml']


def main():
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    archive=output/'laike-wecom-tool-1.0.0.zip'
    sources=[ROOT/name for name in FILES]
    for folder in DIRECTORIES:
        sources.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    sources.extend(ROOT/'artifacts'/name for name in EVIDENCE)
    if any(not p.is_file() for p in sources):raise RuntimeError('交付文件缺失，请先完成验证记录和证据文件')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for file in sorted(set(sources)):
            z.write(file,'laike-wecom-tool/'+file.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if any(any(part in ('.venv','.sender-venv','data','demo-data','sender-data') for part in Path(n).parts) for n in names):
            raise RuntimeError('交付包包含运行数据目录')
        if any(Path(n).name in ('.env','.master-key','.bootstrap-password','sender-config.json') or n.endswith('.db') for n in names):
            raise RuntimeError('交付包包含本机配置或数据库')
        if z.testzip():raise RuntimeError('交付包完整性检查失败')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/(archive.name+'.sha256')).write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    result={'archive':archive.name,'files':len(names),'bytes':archive.stat().st_size,'sha256':digest,'runtime_data_included':False}
    (ROOT/'artifacts'/'release-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
