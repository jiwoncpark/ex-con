"""Script to train the Bayesian GNN

"""
from n2j.trainval_data.raytracers.cosmodc2_raytracer import CosmoDC2Raytracer
from n2j.trainer import Trainer

if __name__ == '__main__':
    # Generate training labels for new healpix
    train_Y_generator = CosmoDC2Raytracer(out_dir='cosmodc2_raytracing_{:d}'.format(10327),
                                          fov=0.85,
                                          healpix=10327,
                                          n_sightlines=50000,  # many more LOS
                                          mass_cut=11.0,
                                          n_kappa_samples=0)  # no sampling
    train_Y_generator.parallel_raytrace()
    train_Y_generator.apply_calibration()

    # Features to compile
    features = ['ra_true', 'dec_true']
    features += ['ellipticity_1_true', 'ellipticity_2_true']
    features += ['size_true']
    features += ['mag_{:s}_lsst'.format(b) for b in 'ugrizY']
    # Features to train on
    sub_features = ['ra_true', 'dec_true']
    sub_features += ['size_true']
    sub_features += ['mag_{:s}_lsst'.format(b) for b in 'i']
    trainer = Trainer('cuda', checkpoint_dir='test_run', seed=1234)
    healpixes = [10450, 10327]
    raytracing_out_dirs = ['cosmodc2_raytracing_{:d}'.format(hp) for hp in healpixes]
    trainer.load_dataset(dict(features=features,
                              raytracing_out_dirs=raytracing_out_dirs,
                              healpixes=healpixes,
                              n_data=[50000, 50000],
                              aperture_size=1.0,
                              stop_mean_std_early=True),
                         sub_features=sub_features,
                         is_train=True,
                         batch_size=100,
                         )
    # FIXME: must be run after train
    trainer.load_dataset(dict(features=features,
                              raytracing_out_dirs=['cosmodc2_raytracing_9559'],
                              healpixes=[9559],
                              n_data=[100],
                              aperture_size=1.0),
                         sub_features=sub_features,
                         is_train=False,
                         batch_size=100,  # FIXME: must be same as train
                         )
    trainer.configure_loss_fn('FullRankGaussianNLL')
    if True:
        trainer.configure_model('GATNet',
                                {'hidden_channels': 256,
                                 'n_layers': 3,
                                 'dropout': 0.0,
                                 'kwargs': {'concat': False, 'heads': 4}})
    trainer.configure_optim({'lr': 1.e-4, 'weight_decay': 1.e-5},
                            {'factor': 0.5, 'min_lr': 1.e-7, 'patience': 10})
    if False:
        trainer.load_state('/home/jwp/stage/sl/n2j/test_run/DoubleGaussianNLL_epoch=0_03-05-2021_23:41.mdl')
    trainer.train(n_epochs=100)
    print(trainer)
