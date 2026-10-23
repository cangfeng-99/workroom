"""Forms for the folder workspace page.

All text fields keep user input verbatim (``strip=False``) so leading and
trailing whitespace in file content survives; name and path safety is enforced
by ``workspaces.services``, not by silent trimming.
"""

from django import forms


class GrantForm(forms.Form):
    """Absolute path typed by the user; authorized only after validation."""

    path = forms.CharField(label='文件夹完整路径', max_length=1024, strip=False)


class NewFileForm(forms.Form):
    """One new file inside the currently listed directory."""

    grant_id = forms.CharField(widget=forms.HiddenInput)
    directory = forms.CharField(required=False, strip=False, widget=forms.HiddenInput)
    name = forms.CharField(label='文件名', max_length=255, strip=False)
    content = forms.CharField(
        label='新文件内容',
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={'rows': 8}),
    )

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault('auto_id', 'new_%s')
        super().__init__(*args, **kwargs)


class SaveForm(forms.Form):
    """Edits for one existing file, tied to the read revision and grant."""

    grant_id = forms.CharField(widget=forms.HiddenInput)
    path = forms.CharField(max_length=1024, strip=False, widget=forms.HiddenInput)
    revision = forms.CharField(max_length=128, widget=forms.HiddenInput)
    content = forms.CharField(
        label='编辑内容',
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={'rows': 16, 'spellcheck': 'false'}),
    )

    def __init__(self, *args, initial_path: str = '', **kwargs) -> None:
        kwargs.setdefault('auto_id', 'edit_%s')
        super().__init__(*args, **kwargs)
        if initial_path and not self.is_bound:
            self.fields['path'].initial = initial_path
