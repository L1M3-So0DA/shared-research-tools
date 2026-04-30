# 硕士生 L4 仓库配置与工作流规范

## 1. L4 的定位

L4 是硕士生个人研发库，保存完整的研发历史、实验分支和碎片化提交。它是 L3 项目小组库的下游仓库，既要跟随L3的最新版本，也要保留个人研发过程。

| 级别 | 仓库角色 | 访问权限 | 主要用途 |
| :--- | :--- | :--- | :--- |
| **L3** | 上游项目小组库 (`l3_upstream`) | 博士生、对应硕士生 | 作为 L4 的起点和同步来源，供项目小组协作使用。 |
| **L4** | 个人研发库 (`l4_origin`) | 硕士生 | 保存完整研发历史、实验分支和碎片化提交。 |

说明：

- 文中的 `main`、`feature_dev`、`release_for_l3` 都是示例分支名，可以按团队规范调整，但同一仓库内要保持一致。
- 只要本地分支和目标仓库没有共同祖先，桥接合并时就需要加 `--allow-unrelated-histories`。这个参数只放行当前这次合并，不会替你建立后续可复用的历史关系。

## 2. 本地远端配置

在硕士生本地工作区里，建议同时挂上 L3 和自己的 L4 仓库。这样既可以跟随 L3 的最新版本，也可以把个人研发历史完整保存到 L4。

### 方案 A：从 L3 创建工作区

```bash
# 1. 克隆 L3，建立本地工作区
git clone git@github.com:<Org>/L3-ProjectGroup.git master_workspace
cd master_workspace

# 2. 将默认远端重命名为 l3_upstream
git remote rename origin l3_upstream

# 3. 挂载自己的 L4 个人研发仓库
git remote add l4_origin git@github.com:<User>/L4-Private.git

# 4. 检查远端是否配置成功
git remote -v
```

### 方案 B：已经有自己的 L4 仓库

```bash
cd existing_repo
git remote rename origin l4_origin
git remote add l3_upstream git@github.com:<Org>/L3-ProjectGroup.git
git remote -v
```

如果本地仓库还没有 `origin`，也可以直接补加远端：

```bash
git remote add l3_upstream git@github.com:<Org>/L3-ProjectGroup.git
git remote add l4_origin git@github.com:<User>/L4-Private.git
git remote -v
```

## 3. 核心工作流

### 3.1 日常研发：L3 -> L4

先把 L3 的最新主干同步到本地，再在个人开发分支上继续提交。日常开发中的每个提交都保留在 L4。

```bash
# 获取 L3 最新状态
git fetch l3_upstream

# 第一次开发时，基于 L3 主干创建开发分支
git checkout -b feature_dev l3_upstream/main

# 后续开发时，先切回开发分支，再合并 L3 的最新主干
git fetch l3_upstream
git checkout feature_dev
git merge l3_upstream/main

# 修改代码后提交
git add .
git commit -m "dev: [过程描述]"

# 将完整研发历史推送到 L4
git push -u l4_origin feature_dev
```

### 3.2 阶段性共享：L4 -> L3（项目小组库）

模块完成后，把开发结果压缩成一个干净的发布提交，再推送回 L3。这里使用 squash merge，是为了只保留共享结果，不暴露研发过程。

```bash
# 获取 L3 最新状态
git fetch l3_upstream

# 以 L3 主干为基底创建/重置本地发布分支
git checkout -B release_for_l3 l3_upstream/main

# 压缩合并开发分支
# 如果当前分支和 L3 没有共同祖先，就加 --allow-unrelated-histories
git merge --allow-unrelated-histories --squash feature_dev

# 提交单个发布记录
git commit -m "Release: [版本号或功能说明]"

# 推送到 L3 主干
git push l3_upstream release_for_l3:main
```

## 4. 分支约定

### L3

- 主干分支：`main`，共享协作基线。
- 远程跟踪分支：`l3_upstream/main`，跟踪L3主干状态。

### L4

- 开发分支：`feature_dev`，个人开发分支，保留完整研发历史。
- 发布分支：`release_for_l3`，压缩后推送到 L3 时使用。
- 远程跟踪分支：`l4_origin/feature_dev`，跟踪个人研发历史。

## 5. 常见问题

### 5.1 无关历史合并失败

**现象**：执行 merge 或 squash merge 时，Git 提示 `fatal: refusing to merge unrelated histories`。  
**原因**：两个仓库在服务端各自初始化过，历史没有共同祖先。  
**处理**：只要当前分支和目标仓库还没有共同祖先，在合并命令中就要显式加上 `--allow-unrelated-histories`。

```bash
git merge --allow-unrelated-histories --squash feature_dev
```

### 5.2 非快进推送被拒绝

**现象**：`git push` 时出现 `non-fast-forward` 拒绝。  
**原因**：远端分支比本地更新，或者远端已有本地没有同步的有效提交。  
**处理**：

- 如果远端只是占位提交，而且确认可以覆盖，可以先 fetch，再用更安全的强推方式：

```bash
git fetch l3_upstream
git push --force-with-lease l3_upstream release_for_l3:main
```

- 如果远端已有 L3 成员或其他协作者的有效提交，不要强推。可以先 fetch，再把远端 `main` 合并到本地 `release_for_l3` 分支上，再正常推送；这样会产生一个合并提交，处理起来更直接：

```bash
git fetch l3_upstream
git checkout release_for_l3
git merge l3_upstream/main
# 如果 merge 过程中产生冲突，先解决冲突并完成合并
git push l3_upstream release_for_l3:main
```

### 5.3 本地仓库已经有自己的提交

如果你已经在 L4 中做过一部分提交，再去接入 L3，上游历史可能需要先对齐。最稳妥的做法是先备份本地分支，再按上面的流程把 L3 接进来，避免直接覆盖已有实验记录。