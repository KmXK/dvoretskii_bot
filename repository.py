import json
import os

from Models.rule import Rule

class Repository(object):
    
    def __init__(self):
        self._init_db()
        self._migrate_db()
    
    def _init_db(self):
        if not os.path.exists('db.json'):
            with open('db.json', 'w', encoding='utf-8') as f:
                f.write(u'{"AdminIds": [***REMOVED***, ***REMOVED***], "rules": []}')
        self.db = json.loads(open('db.json', encoding='utf-8').read())

    def _migrate_db(self):
        if self.db.get('version') is None:
            self.db['version'] = 1
        if self.db.get('army') is None:
            self.db['army'] = []
        self.write_db()

    def write_db(self):
        open('db.json', 'w', encoding='utf-8').write(json.dumps(self.db, default=lambda o: o.__dict__, sort_keys=True, indent=2, ensure_ascii=False))

    # region rules
    @property
    def rules(self):
        return self.db['rules']
    
    def add_rule(self, rule: Rule):
        self.db['rules'].append(rule)
        self.write_db()
    
    def add_many_rules(self, rules: list[Rule]):
        self.db['rules'] += rules
        self.write_db()
        
    def delete_rule(self, rule_id: str):
        self.db['rules'] = [rule for rule in self.db['rules'] if rule['id'] != rule_id]
        self.write_db()
        
    def delete_many_rules(self, rules: list[str]):
        self.db['rules'] = [rule for rule in self.db['rules'] if rule not in rules]
        self.write_db()
    # endregion

    #region admins
    @property
    def admin_ids(self):
        return self.db['AdminIds']
    
    def is_admin(self, user_id):
        return user_id in self.db['AdminIds']
    
    def add_admin(self, admin_id):
        self.db['AdminIds'].append(admin_id)
        self.write_db()
        
    def delete_admin(self, admin_id):
        self.db['AdminIds'] = [admin for admin in self.db['AdminIds'] if admin != admin_id]
        self.write_db()
    #endregion
