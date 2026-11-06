"""Android's web view, with the two things it leaves to its app: a file picker, and the microphone.

Left alone, a file input in a web view does nothing, and a page asking for the microphone is refused without a word. So
Pictures, exports and restoring a backup could not be used on Android, nor Try a call. iOS's web view does both by itself.

A static proxy because WebChromeClient is a class, which mobile/pyproject.toml names for Chaquopy to build. Only imported on
Android (app.py), and a failure to is not fatal: the panel then says files can't be picked (app/utils/compat.py).
"""

from android.app import Activity
from android.content import Intent
from android.content.pm import PackageManager
from android.net import Uri
from android.webkit import PermissionRequest, ValueCallback, WebChromeClient, WebView
from java import Override, jarray, jboolean, jvoid, static_proxy
from java.lang import String

MICROPHONE = "android.permission.RECORD_AUDIO"


class PanelChrome(static_proxy(WebChromeClient)):
    def __init__(self, app):
        super().__init__()
        self.app = app

    @Override(jboolean, [WebView, ValueCallback, WebChromeClient.FileChooserParams])
    def onShowFileChooser(self, view, callback, params):
        pick_files(self.app, callback, params)
        return True

    @Override(jvoid, [PermissionRequest])
    def onPermissionRequest(self, request):
        allow_microphone(self.app, request)


def picker_for(params) -> Intent:
    """The phone's own picker. Every kind of file unless the page named kinds Android knows: an extension (".zip", as the
    exports ask for) means nothing to it and would grey out the very file wanted."""
    intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.setType("*/*")
    kinds = [str(k) for k in (params.getAcceptTypes() or []) if k]
    if kinds and all("/" in k for k in kinds):
        intent.putExtra(Intent.EXTRA_MIME_TYPES, jarray(String)(kinds))
    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE)
    return intent


def picked(code, data):
    """What the picker gave, as the web view wants it: several come in the clip data, one in the data."""
    if code != Activity.RESULT_OK or data is None:
        return None
    uris = []
    clip = data.getClipData()
    if clip is not None:
        uris = [clip.getItemAt(i).getUri() for i in range(clip.getItemCount())]
    elif data.getData() is not None:
        uris = [data.getData()]
    return jarray(Uri)(uris) if uris else None


def pick_files(app, callback, params):
    # The web view is told every time, cancelled or not: left waiting, it never opens a picker again.
    try:
        app._impl.start_activity(picker_for(params), on_complete=lambda code, data: callback.onReceiveValue(picked(code, data)))
    except Exception as exc:
        print(f"[phone] Could not open the file picker: {exc}")
        callback.onReceiveValue(None)


def allow_microphone(app, request):
    """The microphone for the panel and nothing else, asking the phone first if it has not been allowed yet."""
    wanted = PermissionRequest.RESOURCE_AUDIO_CAPTURE
    if wanted not in list(request.getResources()) or not str(request.getOrigin()).startswith(app.panel.rstrip("/")):
        request.deny()
        return
    grant = lambda: request.grant(jarray(String)([wanted]))
    impl = app._impl
    if impl._native_checkSelfPermission(MICROPHONE) == PackageManager.PERMISSION_GRANTED:
        grant()
        return

    def answered(_permissions, results):
        if len(results) and results[0] == PackageManager.PERMISSION_GRANTED:
            grant()
        else:
            request.deny()

    impl.request_permissions(jarray(String)([MICROPHONE]), on_complete=answered)
