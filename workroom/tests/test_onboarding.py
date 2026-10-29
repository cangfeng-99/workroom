"""Personal first-run flow must work without an account, model or Javascript."""
from django.test import TestCase, override_settings

from apps.projects import user_profile
from apps.projects.models import Member, Project, ReplyJob, UserProfile


@override_settings(WORKROOM_MODE='local')
class PersonalOnboardingTests(TestCase):
    def test_empty_install_shows_an_open_first_project_form(self):
        response=self.client.get('/')
        self.assertContains(response,'data-onboarding')
        self.assertContains(response,'创建并进入项目')
        self.assertContains(response,'稍后再选身份')
        self.assertEqual(Project.objects.count(),0)

    def test_create_with_identity_enters_project_and_survives_refresh(self):
        response=self.client.post('/',{'name':'我的作品','goal':'交付一个可演示版本','onboarding_role':'developer'})
        self.assertEqual(response.status_code,302)
        project=Project.objects.get()
        self.assertIn(f'/p/{project.pk}/',response['Location'])
        self.assertIn('welcome=1',response['Location'])
        self.assertEqual(project.owner.username,user_profile.LOCAL_USERNAME)
        self.assertFalse(project.owner.has_usable_password())
        self.assertEqual(UserProfile.objects.get(user=project.owner).role,'developer')
        for _ in range(2):
            page=self.client.get(response['Location'])
            self.assertEqual(page.status_code,200)
            self.assertContains(page,'项目已创建')
            self.assertContains(page,'手动添加任务')
        self.assertEqual(Project.objects.count(),1)
        self.assertEqual(ReplyJob.objects.count(),0)

    def test_skip_identity_keeps_existing_profile_and_needs_no_api(self):
        owner=user_profile.local_user()
        profile=UserProfile.objects.create(user=owner,role='founder',domain='个人产品')
        response=self.client.post('/',{'name':'跳过身份','goal':'先记录想法','onboarding_role':''})
        self.assertEqual(response.status_code,302)
        profile.refresh_from_db()
        self.assertEqual((profile.role,profile.domain),('founder','个人产品'))
        self.assertEqual(ReplyJob.objects.count(),0)

    def test_new_user_can_skip_without_filling_any_profile(self):
        response=self.client.post('/',{'name':'项目','goal':'目标','onboarding_role':''})
        self.assertEqual(response.status_code,302)
        self.assertEqual(UserProfile.objects.count(),0)
        self.assertEqual(Member.objects.filter(kind='human').count(),1)
        self.assertEqual(ReplyJob.objects.count(),0)

    def test_invalid_form_preserves_input_and_creates_nothing(self):
        response=self.client.post('/',{'name':'保留我的项目名','goal':'','onboarding_role':'designer'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'保留我的项目名')
        self.assertContains(response,'value="designer" selected')
        self.assertEqual(Project.objects.count(),0)
        self.assertEqual(UserProfile.objects.count(),0)

    def test_invalid_identity_is_rejected_without_partial_project(self):
        response=self.client.post('/',{'name':'项目','goal':'目标','onboarding_role':'made-up'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'请选择列表中的身份，或稍后再选')
        self.assertEqual(Project.objects.count(),0)

    def test_existing_projects_keep_the_regular_list(self):
        Project.objects.create(name='已有项目',goal_title='继续开发')
        response=self.client.get('/')
        self.assertContains(response,'已有项目')
        self.assertNotContains(response,'data-onboarding')

    def test_new_project_task_is_visible_without_a_named_timeline(self):
        from apps.projects.models import Task
        project=Project.objects.create(name='新项目',goal_title='我的实际目标')
        task=Task.objects.create(project=project,title='先做登录')
        response=self.client.get(f'/p/{project.pk}/?tab=tasks')
        self.assertContains(response,'data-task-outline')
        self.assertContains(response,task.title)
        self.assertContains(response,project.goal_title)

    def test_existing_named_timeline_remains_default_and_graph_is_optional(self):
        from apps.projects.models import Task
        project=Project.objects.create(name='现有项目',goal_title='保留阶段')
        root=Task.objects.create(project=project,title='10 开发路线')
        stage=Task.objects.create(project=project,parent=root,title='第一阶段')
        Task.objects.create(project=project,parent=stage,title='阶段中的任务')
        response=self.client.get(f'/p/{project.pk}/?tab=tasks')
        self.assertContains(response,'class="timeline"')
        self.assertContains(response,'阶段中的任务')
        response=self.client.get(f'/p/{project.pk}/?tab=tasks&view=graph')
        self.assertContains(response,'node-goal')
