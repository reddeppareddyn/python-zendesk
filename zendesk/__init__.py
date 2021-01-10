import requests, json
import logging
import time

class ZendeskError(Exception):
    def __init__(self, message, **kwargs):
        super(ZendeskError, self).__init__(message)
        self.kwargs = kwargs

class Zendesk(object):
    def __init__(self, subdomain, auth=None, field_mapping={}, endpoint="https://{subdomain}.zendesk.com/api/v2", auto_retry=True, timeout=30):
        self.subdomain, self.auth = subdomain, auth
        self.endpoint = endpoint.format(subdomain=subdomain)
        self.field_mapping = field_mapping
        self.session = self.get_session()
        self.auto_retry = True
        self.timeout = timeout
        self.logger = logging.getLogger('zendesk')
        self.ignore_missing_fields = False

    def get_session(self):
        s = requests.session()
        s.auth = self.auth
        return s

    def search(self, query):
        ret = self.get('/search.json', params={'query': query})
        return ret.json

    def get_users(self, email=None, external_id=None):
        assert email or external_id, "must specify either email or external_id!"
        params = {'query': email} if email else {'external_id' : external_id}
        ret = self.get('/users.json', params=params)
        return ret.json['users']

    def create_user(self, **kwargs):
        ret = self.post("/users.json", data={'user': kwargs})
        if ret.json.get('error', '') == 'RecordInvalid':
            raise ValueError(ret.content)
        return ret.json['user']

    def update_user(self, user_id, **kwargs):
        ret = self.put("/users/%d.json" % user_id, data={'user': kwargs})
        if ret.json.get('error', '') == 'RecordInvalid':
            raise ValueError(ret.content)
        try:
            return ret.json['user']
        except Exception:
            raise ValueError(ret.content)

    def request(self, method, url, *args, **kwargs):
        if not url.startswith("http"): url = self.endpoint + url
        ret = self.session.request(method, url, *args, timeout=self.timeout, **kwargs)
        if self.auto_retry and ret.status_code == 429: # rate limit
            retry_after = int(ret.headers['Retry-After'])
            self.logger.warn("Zendesk rate limit reached, retrying after {} seconds: {} {}".format(retry_after, method, url))
            time.sleep(retry_after)
            return self.request(method, url, *args, **kwargs)
        if ret.status_code >= 400:
            raise ZendeskError(u"Bad status: {} {} {} {}".format(method, url, ret.status_code, ret.text), response=ret, method=method, url=url, args=args, kwargs=kwargs)
        try:
            setattr(ret, 'json', json.loads(ret.content))
        except Exception: ret.json = None
        return ret

    def get(self, url, *args, **kwargs):
        return self.request('GET', url, *args, **kwargs)

    def post(self, url, data, *args, **kwargs):
        kwargs['headers'] = kwargs.get('headers', {})
        kwargs['headers']['Content-Type'] = 'application/json'
        return self.request('POST', url, data=json.dumps(data), *args, **kwargs)

    def put(self, url, data, *args, **kwargs):
        kwargs['headers'] = kwargs.get('headers', {})
        kwargs['headers']['Content-Type'] = 'application/json'
        return self.request('PUT', url, data=json.dumps(data), *args, **kwargs)

    def delete(self, url, data, *args, **kwargs):
        kwargs['headers'] = kwargs.get('headers', {})
        kwargs['headers']['Content-Type'] = 'application/json'
        return self.request('DELETE', url, data=json.dumps(data), *args, **kwargs)

    @property
    def fields(self):
        return dict((self.field_mapping.get(v['id'], v['title']), v) for v in self.id_fields.values())

    @property
    def title_fields(self):
        return dict((v['title'], v) for v in self.id_fields.values())

    @property
    def id_fields(self):
        if not hasattr(self, '_id_fields'): self._id_fields = self._get_fields()
        return self._id_fields

    def get_field(self, k):
        fd = self.fields.get(k)
        if not fd: fd = self.id_fields.get(k)
        if not fd: fd = self.title_fields.get(k)
        return fd

    def _get_fields(self):
        ret = self.get('/ticket_fields.json')
        fields = dict((e['id'], e) for e in ret.json['ticket_fields'])
        if 'custom_field_options' in fields:
            fields['options'] = [o['value'] for o in fields['custom_field_options']]
        return fields

    def format_task_data(self, data):
        if 'comment' in data:
            data['comment'] = data['comment'] if isinstance(data['comment'], dict) else {'body' : data['comment'], 'public' : False}
        if 'fields' in data:
            data['custom_fields'] = []
            fields = data.pop('fields')
            for k in fields.keys():
                fd = self.get_field(k)
                v = fields[k]
                if fd is None and self.ignore_missing_fields: continue
                assert fd is not None, "No match for field %s" % k
                assert ('options' not in fd) or (v in fd['options'])
                data['custom_fields'].append({'id' : fd['id'], 'value' : v})
        return data

    def update_ticket(self, ticket_id, **data):
        data = self.format_task_data(data)
        return self.put("/tickets/%s.json" % ticket_id, {'ticket': data})

    def add_tags(self, ticket_id, tags):
        tags = [tags] if isinstance(tags, basestring) else tags
        return self.put("/tickets/%s/tags.json" % ticket_id, {'tags':tags})

    def delete_tags(self, ticket_id, tags):
        tags = [tags] if isinstance(tags, basestring) else tags
        return self.delete("/tickets/%s/tags.json" % ticket_id, {'tags':tags})

    def list_tickets(self, view_id):
        ret = self.get("/views/%s/tickets.json" % view_id)
        return ret.json

    def create_task(self, **data):
        data = self.format_task_data(data)
        data['type'] = 'task'
        return self.post('/tickets.json', {'ticket' : data})

    def get_audits(self, ticket_id):
        return self.get("/tickets/%s/audits.json" % ticket_id).json

    def get_comments(self, ticket_id):
        comments = lambda js: [dict(e, created_at=a['created_at'])  for a in js['audits'] for e in a['events'] if e['type'] == 'Comment']
        return comments(self.get_audits(ticket_id))

    def get_incremental_tickets(self, start_time, sample=False):
        if sample:
            return self.get('/incremental/tickets/sample.json?start_time={}'.format(start_time))
        else:
            return self.get('/incremental/tickets.json?start_time={}'.format(start_time))

class ZendeskSocks(Zendesk):
    def get_session(self):
        import requesocks
        s = requesocks.session()
        s.proxies = {'https': 'socks5://127.0.0.1:9090'}
        s.auth = self.auth
        return s

