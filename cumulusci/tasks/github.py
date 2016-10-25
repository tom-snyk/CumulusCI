from datetime import datetime
from github3 import login
from cumulusci.core.tasks import BaseTask

class BaseGithubTask(BaseTask):

    def _init_task(self):
        self.github_config = self.project_config.keychain.get_github()
        self.github = login(
            username=self.github_config.username,
            password=self.github_config.password,
        )

    def get_repo(self):
        return self.github.repository(
            self.project_config.repo_owner,
            self.project_config.repo_name,
        )

class PullRequests(BaseGithubTask):
    
    def _run_task(self):
        repo = self.get_repo()
        for pr in repo.iter_pulls(state='open'):
            self.logger.info('#{}: {}'.format(pr.number, pr.title))

class CloneTag(BaseGithubTask):

    task_options = {
        'src_tag': {
            'description': 'The source tag to clone.  Ex: beta/1.0-Beta_2',
            'required': True,
        },
        'tag': {
            'description': 'The new tag to create by cloning the src tag.  Ex: release/1.0',
            'required': True,
        },
    }
    
    def _run_task(self):
        repo = self.get_repo()
        ref = repo.ref('tags/{}'.format(self.options['src_tag']))
        src_tag = repo.tag(ref.object.sha)
        if not src_tag:
            logger.error('Tag {} not found'.format(self.options['src_tag']))
            return

        tag = repo.create_tag(
            tag = self.options['tag'],
            message = 'Cloned from {}'.format(self.options['src_tag']),
            sha = src_tag.sha,
            obj_type = 'commit',
            tagger = {
                'name': self.github_config.username,
                'email': self.github_config.email,
                'date': '{}Z'.format(datetime.now().isoformat()),
            },
        )
        self.logger.info('Tag {} created by cloning {}'.format(self.options['tag'], self.options['src_tag']))

        return tag

class CreateRelease(BaseGithubTask):

    task_options = {
        'version': {
            'description': "The managed package version number.  Ex: 1.2",
            'required': True,
        },
        'message': {
            'description': "The message to attach to the created git tag",
        },
        'commit': {
            'description': "Override the commit used to create the release.  Defaults to the current local HEAD commit",
        },
        'draft': {
            'description': "Set to True to create a draft release.  Defaults to False",
        },
    }
    
    def _run_task(self):
        repo = self.get_repo()

        for release in repo.iter_releases():
            if release.name == self.options['version']:
                self.logger.error('Release {} already exists at {}'.format(release.name, release.html_url))
                return

        commit = self.options.get('commit', self.project_config.repo_commit)
        if not commit:
            self.logger.error('Could not detect the current commit from the local repo')
            return

        version = self.options['version']
        tag_name = self.project_config.get_tag_for_version(version)

        tag = repo.create_tag(
            tag = tag_name,
            message = 'Release of version {}'.format(version),
            sha = commit,
            obj_type = 'commit',
            tagger = {
                'name': self.github_config.username,
                'email': self.github_config.email,
                'date': '{}Z'.format(datetime.now().isoformat()),
            },
        )

        draft = self.options.get('draft', False) in [True, 'True', 'true']
        prerelease = 'Beta' in version

        release = repo.create_release(
            tag_name = tag_name,
            target_commitish = commit,
            name = version,
            draft = draft,
            prerelease = prerelease,
        )

        self.logger.info('Created release {} at {}'.format(release.name, release.html_url))

class MergeBranch(BaseGithubTask):

    task_options = {
        'commit': {
            'description': "The commit to merge into feature branches.  Defaults to the current head commit.",
        },
        'source_branch': {
            'description': "The source branch to merge from.  Defaults to project__git__default_branch.",
        },
        'branch_prefix': {
            'description': "The prefix of branches that should receive the merge.  Defaults to project__git__prefix_feature",
        },
    }

    def _run_task(self):
        repo = self.get_repo()

        commit = self.options.get('commit', self.project_config.repo_commit)
        branch_prefix = self.options.get('branch_prefix', self.project_config.project__git__prefix_feature)
        source_branch = self.options.get('source_branch', self.project_config.project__git__default_branch)

        head_branch = repo.branch(source_branch)
        if not repo:
            self.logger.error('Branch {} not found'.format(source_branch))

        # Get existing pull requests targeting a target branch
        existing_prs = []
        for pr in repo.iter_pulls(state='open'):
            if pr.base.ref.startswith(branch_prefix):
                existing_prs.append(pr.base.ref)
        
        targets = []
        for branch in repo.iter_branches():
            if not branch.name.startswith(branch_prefix):
                self.logger.info('Skipping branch {}: does not match prefix {}'.format(branch.name, branch_prefix))
                continue
            if branch.name == source_branch:
                self.logger.info('Skipping branch {}: is source branch'.format(branch.name))
                continue
               
            compare = repo.compare_commits(branch.commit.sha, commit)
            if not compare.files:
                self.logger.info('Skipping branch {}: no file diffs found'.format(branch.name))
                continue
   
            try: 
                result = repo.merge(branch.name, source_branch)
                self.logger.info('Merged {} commits into {}'.format(compare.behind_by, branch.name))
            except GithubError as e:
                if e.code != 409:
                    raise e

                if branch.name in existing_prs:
                    self.logger.info('Merge conflict on branch {}: merge PR already exists'.format(branch.name))
                    continue 

                pull = repo.create_pull(
                    title = 'Merge {} into {}'.format(source_branch, branch.name),
                    base = branch.name,
                    head = source_branch,
                    body = 'This pull request was automatically generated because an automated merge hit a merge conflict',
                )

                self.logger.info('Merge conflict on branch {}: created pull request #{}'.format(branch.name, pull.number))