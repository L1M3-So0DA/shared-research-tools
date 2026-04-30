# 实验室多级 Git 仓库权限隔离与工作流规范

## 1. 架构拓扑模型

本文描述的是三仓库、三权限层的逻辑隔离方案，用于把核心主干、个人研发过程和项目小组共享版本分开管理。

| 级别 | 仓库角色 | 访问权限 | 主要用途 |
| :--- | :--- | :--- | :--- |
| **L1** | 核心主干库 (`l1_upstream`) | 导师、博士生 | 保存项目主干代码，历史尽量保持线性、整洁。 |
| **L2** | 个人研发库 (`l2_origin`) | 博士生 | 保存完整研发过程，包括碎片化提交和实验性分支。 |
| **L3** | 项目小组库 (`l3_downstream`) | 博士生、硕士生 | 保存已脱敏的阶段性共享版本，供项目小组协作使用。 |

说明：

- 文中的 `main`、`feature_dev`、`release_for_master`、`l1_main` 都是示例分支名。可以按团队规范调整，但同一仓库内要保持一致。
- 只要本地分支和目标仓库没有共同祖先，跨仓库桥接时就需要在合并命令里加上 `--allow-unrelated-histories`。squash merge 不会替你建立后续可复用的历史关联。

## 2. 本地远端配置

在博士生本地工作区中，可以把三个仓库同时挂到一个目录下，便于同步和发布。下面示例假设从 L1 克隆出工作区；如果你手上已经是现成的 L2 仓库，只需补加远端即可。

```bash
# 1. 克隆 L1 核心仓库，建立本地工作区
git clone git@github.com:<Org>/L1-Core.git lab_workspace
cd lab_workspace

# 2. 将默认远端重命名为 l1_upstream
git remote rename origin l1_upstream

# 3. 挂载 L2 个人研发仓库
git remote add l2_origin git@github.com:<User>/L2-Private.git

# 4. 挂载 L3 项目小组仓库
git remote add l3_downstream git@github.com:<Org>/L3-ProjectGroup.git

# 5. 检查远端是否配置成功
git remote -v
```

如果本地已经是一个现成仓库，可以直接补加远端：

```bash
cd existing_repo
git remote add l1_upstream git@github.com:<Org>/L1-Core.git
git remote add l3_downstream git@github.com:<Org>/L3-ProjectGroup.git
git remote -v
```

## 3. 核心工作流

### 3.1 日常研发：L1 -> L2

先把 L1 的最新主干同步到本地，再在个人开发分支上继续提交。研发过程中的每个提交都保留在 L2。

```bash
# 获取 L1 最新状态
git fetch l1_upstream

# 第一次开发时，基于 L1 主干创建开发分支
git checkout -b feature_dev l1_upstream/main

# 后续开发时，先切回开发分支，再合并 L1 的最新主干
git fetch l1_upstream
git checkout feature_dev
git merge l1_upstream/main

# 修改代码后提交
git add .
git commit -m "dev: [过程描述]"

# 将完整研发历史推送到 L2
git push -u l2_origin feature_dev
```

### 3.2 阶段性共享：L2 -> L3

模块完成后，把开发结果压缩成一个干净的发布提交，再推送到 L3。这里使用 squash merge，是为了只保留共享结果，不暴露研发过程。

```bash
# 获取 L3 最新状态
git fetch l3_downstream

# 以 L3 主干为基底创建/重置本地发布分支
git checkout -B release_for_master l3_downstream/main

# 压缩合并开发分支
# 如果当前两个仓库没有共同祖先，就加 --allow-unrelated-histories
git merge --allow-unrelated-histories --squash feature_dev

# 提交单个发布记录
git commit -m "Release: [版本号或功能说明]"

# 推送到 L3 主干
git push l3_downstream release_for_master:main
```

### 3.3 最终入库：L2 -> L1

项目成熟后，将最终成果压缩合并回 L1 主干，保持核心仓库历史简洁。

```bash
# 更新 L1 主干状态
git fetch l1_upstream
git checkout -B l1_main l1_upstream/main

# 压缩合并开发分支
# 如果当前开发分支与 L1 没有共同祖先，就加 --allow-unrelated-histories
git merge --allow-unrelated-histories --squash feature_dev

# 提交正式入库记录
git commit -m "Feature: [核心功能说明]"

# 推送到 L1
git push l1_upstream l1_main:main
```

## 4. 分支约定

### L1

- 主干分支：`main`，核心代码库，尽量保持线性历史。

### L2

- 开发分支：`feature_dev`，个人开发分支，保留完整研发历史。
- 发布分支：`release_for_master`，压缩后推送到 L3 时使用。
- 入库分支：`l1_main`，压缩后推送到 L1 时使用。
- 远程跟踪分支：`l1_upstream/main`，跟踪 L1 主干。
- 远程跟踪分支：`l3_downstream/main`，跟踪 L3 主干。

### L3

- 主干分支：`main`，脱敏后的共享分支，供项目小组成员协作使用。

## 5. 异常处理

### 5.1 无关历史合并失败

**现象**：执行 merge 或 squash merge 时，Git 提示 `fatal: refusing to merge unrelated histories`。  
**原因**：两个仓库在服务端各自初始化过，历史没有共同祖先。  
**处理**：只要两个分支之间还没有共同祖先，在合并命令中就要显式加上 `--allow-unrelated-histories`。这个参数只允许当前这次合并继续执行，不会让后续分支自动共享历史。

```bash
git merge --allow-unrelated-histories --squash feature_dev
```

### 5.2 非快进推送被拒绝

**现象**：`git push` 时出现 `non-fast-forward` 拒绝。  
**原因**：远端分支比本地更新，或者远端已有本地没有同步的有效提交。  
**处理**：

- 如果远端只是占位提交，而且确认可以覆盖，可以先 fetch，再用更安全的强推方式：

```bash
git fetch l3_downstream
git push --force-with-lease l3_downstream release_for_master:main
```

- 如果远端已有项目小组成员或其他协作者的有效提交，不要强推。可以先 fetch，再把远端 `main` 合并到本地 `release_for_master` 分支上，再正常推送；这样会产生一个合并提交，处理起来更直接：

```bash
git fetch l3_downstream
git checkout release_for_master
git merge l3_downstream/main
# 如果 merge 过程中产生冲突，先解决冲突并完成合并
git push l3_downstream release_for_master:main
```