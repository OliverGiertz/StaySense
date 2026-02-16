# GitHub Wiki Publish

Status: Wiki-Entwürfe liegen in `docs/wiki/`.

## Voraussetzung

In GitHub muss das Wiki im Repo aktiviert sein:

- Repo `StaySense` -> `Settings` -> `Features` -> `Wikis` aktivieren

Hinweis: Wenn deaktiviert, leitet `https://github.com/OliverGiertz/StaySense/wiki` nur auf das Repo zurück und `StaySense.wiki.git` ist nicht erreichbar.

## Einmaliger Publish

```bash
cd /tmp
rm -rf staysense-wiki-publish
mkdir -p staysense-wiki-publish
cd staysense-wiki-publish

git init
cp -R /Users/oliver/StaySense/docs/wiki/. .
git add .
git commit -m "Initialize StaySense wiki"
git branch -M master
git remote add origin https://github.com/OliverGiertz/StaySense.wiki.git
git push -u origin master
```

## Update Publish (nach Änderungen)

```bash
cd /tmp/staysense-wiki-publish
cp -R /Users/oliver/StaySense/docs/wiki/. .
git add .
git commit -m "Update wiki docs"
git push
```
