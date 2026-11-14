import ast, json, sys
# Static read: the ids of the backend's scenario list, without importing backend code.
def ids(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign): targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name): targets = [node.target.id]
        for name in targets:
            if name in ("SCENARIOS", "SECRETARY") and isinstance(node.value, ast.List):
                out = []
                for el in node.value.elts:
                    if isinstance(el, ast.Dict):
                        for k, v in zip(el.keys, el.values):
                            if isinstance(k, ast.Constant) and k.value == "id" and isinstance(v, ast.Constant): out.append(v.value)
                    elif isinstance(el, ast.Call):
                        for kw in el.keywords:
                            if kw.arg == "id" and isinstance(kw.value, ast.Constant): out.append(kw.value.value)
                        if el.args and isinstance(el.args[0], ast.Constant) and not any(kw.arg=="id" for kw in el.keywords): out.append(el.args[0].value)
                found[name] = (out, len(node.value.elts))
    return found
res = {}
for label, path in [a.split("=",1) for a in sys.argv[1:]]:
    f = ids(path); res[label] = f
    print(label, {k: (len(v[0]), v[1]) for k, v in f.items()})
allid = {l: set(i for v in f.values() for i in v[0]) for l, f in res.items()}
labels = list(allid)
if len(labels) >= 3:
    a, b, m = labels[0], labels[1], labels[2]
    print("union of parents:", len(allid[a] | allid[b]), "integrated:", len(allid[m]))
    print("missing from integrated:", sorted((allid[a] | allid[b]) - allid[m]))
    print("only in integrated:", sorted(allid[m] - (allid[a] | allid[b])))
    print("only in", a, len(allid[a] - allid[b]), "only in", b, len(allid[b] - allid[a]))
