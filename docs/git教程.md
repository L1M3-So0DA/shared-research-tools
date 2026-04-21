# git使用教程

- 以VSCode为例，其他IDE类似

## Git基础操作

### 安装

- Windows：下载Git for Windows，安装时选择使用Git Bash作为默认终端

安装完成后，在VSCode中打开终端，输入以下命令验证安装：

```bash
git --version
```

如果显示Git版本号，说明安装成功。
之后执行以下命令配置Git的用户名和邮箱，方便在提交代码时记录作者信息：

```bash
git config --global user.name "Your Name"
git config --global user.email "test@example.com"
```

### 开始

- 初始化仓库

打开VSCode终端，进入项目目录，执行以下命令，将一个现有项目添加到 Git 仓库，也可直接在VSCode中点击左侧活动栏的"源代码管理"图标，选择"初始化存储库"按钮，完成后会自动执行以下命令：

```bash
git init
```

- 克隆仓库

如果项目已经托管在远程仓库（如GitHub），可以使用以下命令克隆仓库到本地，也可直接在VSCode中点击左侧活动栏的"源代码管理"图标，选择"克隆存储库"按钮，完成后会自动执行以下命令（建议采取该方式，克隆自己的github仓库，方便后续进行代码分享和版本控制。）：

```bash
git clone <repository_url>
```

- 添加辅助文件
在项目根目录下创建一个 `.gitignore` 文件，添加相关内容以忽略不必要的文件：

```gitignore
# 忽略MAT文件
*.mat
# 忽略图片文件
*.png
# 忽略指定目录下的所有文件
data/
```

### 提交更改

在VSCode中，修改文件后，左侧活动栏的"源代码管理"图标会显示有更改。点击该图标，可以看到所有更改的文件。选择需要提交的文件，点击旁边的 `+` 号将其加入暂存区，然后在消息框输入提交信息，点击"提交"按钮完成提交。
也可以在终端中使用以下命令提交更改：

```bash
git add .                   # 暂存所有更改
git commit -m "描述信息"    # 提交暂存区内容
```

此时，提交的更改会被记录在本地仓库中，可以随时回滚到之前的版本。

**提交规范**

为了保持提交历史的清晰和有意义，建议遵循以下提交规范：

- 使用简洁明了的提交信息，描述所做的更改
- 使用动词开头，如"添加"、"修复"、"优化"等
- 如果提交涉及多个更改，可以使用分号分隔不同的更改点
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 代码重构
- `docs`: 文档更新
- `test`: 测试相关
以下为示例提交信息：

```markdown
feat: 添加数据预处理脚本
fix: 修复数据加载错误
docs: 更新使用说明文档
```

### 版本回滚

如果需要查看之前的提交历史，可以直接点击左侧活动栏的"源代码管理"图标，安装 **GitLens** 后，可以可视化查看提交历史，并且可以方便地回滚到指定版本。

如果需要回滚到之前的版本，可以右键点击指定的提交，选择"签出"，也可以使用以下命令：

```bash
git log --oneline           # 查看提交历史，找到需要回滚的版本号
git checkout <commit_id>    # 回滚到指定版本
```

回滚后，当前工作区会切换到指定版本的状态，可以进行修改或查看代码。如果需要回到主分支最新版本，可以使用以下命令，也可以直接在VSCode中选择目标节点，右键点击选择"签出"：

```bash
git checkout main            # 切换回主分支
```

*注意：在回滚之前，请确保已经保存了当前工作区的更改，以免丢失未提交的修改。在回滚之后，如果修改了代码，需要重新提交到新的分支或节点。*

### 撤销提交

如果需要撤销最近的提交，可以使用以下命令：

```bash
git reset --soft HEAD~1    # 撤销最近的提交，但保留更改
git reset --hard HEAD~1    # 撤销最近的提交，并丢弃更改
```

*注意：使用 `--hard` 选项会丢失未提交的更改，请谨慎使用。*

### 远程操作

如果需要将本地仓库的更改推送到远程仓库，可以点击Vscode中左侧活动栏的"源代码管理"图标，选择"推送/发布分支"按钮，也可以使用以下命令：

```bash
git push origin main        # 推送到远程仓库的主分支
```

当创建了新的分支后，同样点击Vscode中左侧活动栏的"源代码管理"图标，选择"推送/发布分支"按钮，也可以使用以下命令推送到远程仓库：

```bash
git push origin <branch_name>    # 推送到远程仓库的指定分支
```

如果需要从远程仓库拉取最新的更改，可以点击Vscode中左侧活动栏的"源代码管理"图标，选择"拉取"按钮，也可以使用以下命令：

```bash
git pull origin main        # 从远程仓库的主分支拉取最新更改
```

*注：在vscode中有“拉取”和“从所有远程储存库中拉取”选项，一般情况下选择“拉取”，后续章节会介绍“从所有远程储存库中拉取”。*

## 分支管理

分支是Git中非常重要的概念，可以让我们在同一个项目中同时进行多个开发任务，而不会互相干扰。

### 创建分支

在VSCode中，有多种创建分支方法

- 可以通过左侧活动栏的"源代码管理"图标，点击上部储存库的`...`，选择`分支->创建分支`，输入分支名称后回车即可创建新分支。
- 也可以直接在VSCode中选择任意节点，右键点击选择"从此处创建分支"，输入分支名称后回车即可创建新分支。
- 还可以直接在终端中使用以下命令创建新分支：

```bash
git branch <branch_name>    # 创建新分支
git branch feature-xyz    # 创建名为feature-xyz的新分支
```

### 切换分支

在VSCode中，点击左侧活动栏的"源代码管理"图标，在上部储存库的分支名称旁边点击，选择需要切换的分支即可。
也可以直接在终端中使用以下命令切换分支：

```bash
git checkout <branch_name>    # 切换分支
git checkout feature-xyz    # 切换到名为feature-xyz的分支
git checkout -b <branchname>    # 创建并切换到新分支
git checkout -b feature-xyz    # 创建并切换到名为feature-xyz的新分支
```

### 查看分支

在VSCode中，点击左侧活动栏的"源代码管理"图标，在上部储存库的分支名称旁边点击，可以看到所有分支列表。
也可以直接在终端中使用以下命令查看所有分支：

```bash
git branch    # 查看本地分支
git branch -r    # 查看远程分支
git branch -a    # 查看所有分支
```

### 合并分支

在VSCode中，点击左侧活动栏的"源代码管理"图标，切换到目标分支，在上部储存库的`...`点击，选择`分支->合并`，之后选择需合并的分支即可。
当合并过程中出现冲突时，Git 会标记冲突文件，需要手动解决冲突。

也可以直接在终端中使用以下命令合并分支：

```bash
git merge <branch_name>    # 合并指定分支到当前分支
git merge feature-xyz    # 合并名为feature-xyz的分支到当前分支
```

*注意：在合并分支之前，请确保已经保存了当前工作区的更改，以免丢失未提交的修改。*

此处容易混淆，举例说明：
创建两个分支`tree1`和 `tree2`，

```bash
git branch tree1    # 创建tree1分支
git branch tree2    # 创建tree2分支
```

分别在`tree1`和`tree2`上进行开发不同的功能。在`tree1`上开发了功能1，在`tree2`上开发了功能2。现在需要将`tree2`上的功能2合并到`tree1`上，即`tree1<-tree2`。先切换到`tree1`分支，再执行选择`tree2`进行合并。这样只修改了`tree1`分支的内容，同时拥有了功能1和功能2；`tree2`保持不变，仍然只有功能2：

```bash
git checkout tree1    # 切换到tree1分支
git merge tree2    # 将tree2分支合并到tree1分支
```

### 删除分支

在VSCode中，点击左侧活动栏的"源代码管理"图标，在上部储存库的分支名称旁边`...`点击`分支->删除分支`，选择需要删除的分支，点击即可。

```bash
git branch -d <branch_name>    # 删除本地分支
git branch -D <branch_name>    # 强制删除本地分支
```

*注意：在删除分支时，请确保已经合并了该分支的更改，以免丢失未合并的修改。*

## 进阶操作

### git stash 临时保存工作进度

git stash 命令允许你临时保存当前工作目录的更改，以便你可以切换到其他分支或处理其他任务。

```bash
git stash       # 保存当前工作进度
git stash list      # 查看所有保存的进度
git stash apply     # 恢复最近保存的进度
git stash apply stash@{1}    # 恢复指定的进度
git stash drop stash@{0}     # 删除指定的进度
git stash clear     # 删除所有保存的进度
```

### git Cherry-Pick 挑拣

git cherry-pick 命令允许你选择特定的提交并将其应用到当前分支。它在需要从一个分支移植特定更改到另一个分支时非常有用。

在VScode中，点击左侧活动栏的"源代码管理"图标，安装 **GitLens** 后，可以可视化查看提交历史，右键点击需要挑拣的提交，选择"Cherry-Pick(挑拣)"，即可将该提交应用到当前分支。
也可以直接在终端中使用以下命令：

```bash
git cherry-pick <commit_id>    # 将指定提交应用到当前分支
git cherry-pick abc1234    # 将提交ID为abc1234的提交应用到当前分支
```

### git worktree 工作树

git worktree 命令允许你在同一个 Git 仓库下，同时检出多个工作目录。每个工作目录可以对应不同的分支，适合并行开发、临时修复问题，或者在不切换当前目录的情况下查看另一个分支的代码。

### 添加工作树

在终端中使用以下命令，可以把某个分支检出到新的目录中：

```bash
git worktree add <path> <branch_name>    # 将指定分支检出到新的目录
git worktree add ../demo-feature feature-xyz    # 将feature-xyz分支检出到../demo-feature目录
```

如果指定的分支还不存在，也可以直接创建并检出一个新分支：

```bash
git worktree add -b <branch_name> <path>    # 创建新分支并检出到新的目录
git worktree add -b feature-new ../feature-new    # 创建feature-new分支并检出到../feature-new目录
```

### 查看工作树

如果当前仓库里已经挂载了多个工作目录，可以使用以下命令查看：

```bash
git worktree list    # 查看所有工作树
```

### 删除工作树

当某个工作目录不再需要时，可以先回到其他目录，再删除对应的工作树：

```bash
git worktree remove <path>    # 删除指定工作树
git worktree remove ../demo-feature    # 删除../demo-feature目录对应的工作树
```

如果工作树目录已经手动删除，也可以使用清理命令移除仓库里的记录：

```bash
git worktree prune    # 清理失效的工作树记录
```

*注意：同一个分支不能同时被多个工作树检出。使用 worktree 之前，需要先确认目标分支没有被其他工作目录占用。工作树适合并行处理不同任务，但文件路径会变多，管理时要注意不要混淆。*
