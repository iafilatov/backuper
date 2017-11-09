from backuper.modules.cloud.amazon import get_amazon_client
from backuper.utils.validate import ValidateBase, validate_empty_snapshots
from backuper.utils import get_msg
from backuper.utils.constants import amazon_regions, wait_timeout, engines, \
                                     snapshot_types, fail_on_error as f_on_e
from backuper.utils.filters import main as f_main
from time import sleep
from multiprocessing import Process


class ValidateRDS(ValidateBase):

    def params_validate(self, **kwargs):

        if kwargs['action'] == 'create':
            parameters_schema = self.tr.Dict({
                self.tr.Key('region'): self.tr.Enum(*amazon_regions),
                self.tr.Key('snapshot_type'): self.tr.Enum(*snapshot_types),
                self.tr.Key('engine'): self.tr.Enum(*engines['rds']),
                self.tr.Key('snapshot_id'): self.tr.String,
                self.tr.Key('database_id'): self.tr.String,
                self.tr.Key('copy_to_region', optional=True): self.tr.Enum(
                    *amazon_regions),
                self.tr.Key('wait_timeout', optional=True): self.tr.Int
            })

        if kwargs['action'] == 'restore':
            parameters_schema = self.tr.Dict({
                self.tr.Key('region'): self.tr.Enum(*amazon_regions),
                self.tr.Key('engine'): self.tr.Enum(*engines['rds']),
                self.tr.Key('snapshot_type'): self.tr.Enum(*snapshot_types),
                self.tr.Key('snapshot_id'): self.tr.String,
                self.tr.Key('database_id'): self.tr.String,
                self.tr.Key('wait_timeout', optional=True): self.tr.Int
            })

        if kwargs['action'] == 'delete':
            parameters_schema = self.tr.Dict({
                self.tr.Key('region'): self.tr.Enum(*amazon_regions),
                self.tr.Key('engine'): self.tr.Enum(*engines['rds']),
                self.tr.Key('snapshot_type'): self.tr.Enum(*snapshot_types),
                self.tr.Key('snapshot_id'): self.tr.String
            })

        parameters_schema(kwargs['parameters'])


class Main(object):

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.parameters = self.kwargs['parameters']
        self.validate = ValidateRDS()
        self.client = get_amazon_client(
            self.kwargs['type'], self.parameters['region'])

    def get_snapshots(self):

        response = self.client.describe_db_snapshots(
            Engine=self.parameters['engine'])

        return response

    def create_snapshot(self):

        response = self.client.create_db_snapshot(
            Engine=self.parameters['engine'],
            DBSnapshotIdentifier=self.parameters['snapshot_id'],
            DBInstanceIdentifier=self.parameters['database_id']
        )
        return response

    def restore_from_snapshot(self):

        response = self.client.restore_db_instance_from_db_snapshot(
            Engine=self.parameters['engine'],
            DBSnapshotIdentifier=self.parameters['snapshot_id'],
            DBInstanceIdentifier=self.parameters['database_id']
        )

        return response

    def instance_is_available(self):

        instance = self.client.describe_db_instances(
            Engine=self.parameters['engine'],
            DBInstanceIdentifier=self.parameters['database_id'])
        status = instance['DBInstances'][0]['DBInstanceStatus']

        return status

    def delete_snapshot(self, snapshots):

        r = []
        for snapshot in snapshots:
            response = self.client.delete_db_snapshot(
                Engine=self.parameters['engine'],
                DBSnapshotIdentifier=snapshot['DBSnapshotIdentifier']
            )
            print(get_msg(self.kwargs['type']) +
                  self.kwargs['action'] + ' is in progress...\n')
            r.append(response)

        return r

    def copy_snapshot(self, resource, region):

        source_db_snapshot_identifier = resource['DBSnapshot']['DBSnapshotArn']
        self.client = get_amazon_client(self.kwargs['type'], region)
        response = self.client.copy_db_snapshot(
            Engine=self.parameters['engine'],
            SourceDBSnapshotIdentifier=source_db_snapshot_identifier,
            TargetDBSnapshotIdentifier=self.parameters['snapshot_id'],
            CopyTags=True,
            SourceRegion=self.parameters['region']
        )

        return response

    def snapshot_status(self, snapshot_id, region):

        self.client = get_amazon_client(self.kwargs['type'], region)
        snapshots = self.get_snapshots()
        for snapshot in snapshots['DBSnapshots']:
            if snapshot['DBSnapshotIdentifier'] == snapshot_id:
                status = snapshot['Status']
        return status

    def wait_snapshot(self, snapshot_id, region):

        if self.parameters.get('wait_timeout') is None:
            counter = wait_timeout
        else:
            counter = self.parameters['wait_timeout']

        print(get_msg(self.kwargs['type']) +
              self.kwargs['action'] + ' is in progress...\n')
        while counter >= 0:
            status = self.snapshot_status(snapshot_id, region)
            if status == 'available':
                print(get_msg(self.kwargs['type']) +
                      '{} snapshot is available in region...\n'.format(
                          snapshot_id))
                break
            else:
                sleep(30)
                counter -= 30

    def filter_snapshots_by_type(self, snapshots, snapshot_type):

        filtered = []
        for snapshot in snapshots['DBSnapshots']:
            if snapshot['SnapshotType'] == snapshot_type:
                filtered.append(snapshot)
        return filtered

    def adapted_snapshots(self, snapshots):

        for snapshot in snapshots:
            snapshot['snapshotName'] = snapshot['DBSnapshotIdentifier']
            snapshot['creationTime'] = snapshot['SnapshotCreateTime']
        return snapshots

    def run(self):

        if self.kwargs['parameters'].get('fail_on_error') is None:
            fail_on_error = f_on_e
        else:
            fail_on_error = self.kwargs['parameters'].get('fail_on_error')

        if self.kwargs['action'] == 'create':
            resource = self.create_snapshot()
            self.wait_snapshot(
                self.parameters['snapshot_id'], self.parameters['region'])
            if self.parameters.get('copy_to_region') is not None:
                jobs = []
                for region in self.parameters.get('copy_to_region'):
                    self.copy_snapshot(resource, region)
                    p = Process(target=self.wait_snapshot,
                                args=(self.parameters['snapshot_id'], region))
                    jobs.append(p)
                    p.start()

        if self.kwargs['action'] == 'delete':

            snapshots = self.get_snapshots()
            validate_empty_snapshots(snapshots['DBSnapshots'],
                                     get_msg(self.kwargs['type']) + ' There are no snapshots in {} region...\n'.format(self.parameters['region']),
                                     fail_on_error)

            if self.parameters['snapshot_type'] != 'all':
                snapshots_by_type = self.filter_snapshots_by_type(
                    snapshots, self.parameters['snapshot_type'])
            else:
                snapshots_by_type = [
                    snapshot for snapshot in snapshots['DBSnapshots']]

            validate_empty_snapshots(snapshots_by_type, get_msg(self.kwargs['type']) +
                                     ' There are no {} snapshots in {} region...\n'.format(self.parameters['snapshot_type'],
                                                                                           self.parameters['region']),
                                     fail_on_error)

            adapted = self.adapted_snapshots(snapshots_by_type)

            snapshots_filtered = f_main(
                self.parameters.get('filters'), adapted)

            self.delete_snapshot(snapshots_filtered)

        # if self.kwargs['action'] == 'restore':
        #     restore = self.restore_from_snapshot()
        #     print(get_msg(self.kwargs['type']) +
        #           self.kwargs['action'] + ' is in progress...\n')
        #     i = 0
        #     while i != 'available':
        #         i = self.instance_is_available()
        #         sleep(60)
        #
        # print(get_msg(self.kwargs['type']) + self.kwargs['action'] +
        #       ' completed in {} region...\n'.format(self.parameters['region']))
