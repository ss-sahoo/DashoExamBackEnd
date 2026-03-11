from accounts.utils import get_current_db

class InstituteRouter:
    """
    A router to control all database operations on models for multi-tenancy.
    """
    
    # Models that should always stay in the 'default' (shared) database
    SHARED_MODELS = {
        'accounts': ['institute', 'user', 'devicesession', 'activitylog'],
        'contenttypes': None, # All models in this app
        'auth': None,        # All models in this app
        'sessions': None,    # All models in this app
        'admin': None,       # All models in this app
    }

    def db_for_read(self, model, **hints):
        """
        Attempts to read models go to the tenant database unless they are shared.
        """
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        
        if app_label in self.SHARED_MODELS:
            shared_models = self.SHARED_MODELS[app_label]
            if shared_models is None or model_name in shared_models:
                return 'default'
        
        return get_current_db()

    def db_for_write(self, model, **hints):
        """
        Attempts to write models go to the tenant database unless they are shared.
        """
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        
        if app_label in self.SHARED_MODELS:
            shared_models = self.SHARED_MODELS[app_label]
            if shared_models is None or model_name in shared_models:
                return 'default'
        
        return get_current_db()

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if both objects are in the same database.
        Note: Django doesn't support cross-db foreign keys well.
        """
        db1 = self.db_for_read(obj1.__class__)
        db2 = self.db_for_read(obj2.__class__)
        
        # If both are in the same DB, allow the relation
        if db1 == db2:
            return True
        
        # Cross-db relations are tricky. For 'Institute' and 'User' in 'default',
        # we often need to allow relations from tenant DB models to them.
        # But databases themselves usually don't support foreign keys across DBs.
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Ensure shared models only migrate to 'default'.
        Tenant models should migrate to both if we want them available.
        """
        if app_label in self.SHARED_MODELS:
            shared_models = self.SHARED_MODELS[app_label]
            if shared_models is None or model_name in shared_models:
                return db == 'default'
        
        # If it's not a shared model, it can be migrated to tenant DBs
        # (Assuming we manage tenant migrations carefully)
        return True
